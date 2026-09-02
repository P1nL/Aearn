import type { ApiError } from "./core";
import type { ExerciseAttemptOutcome, ModelCodeReviewSubmission, ModelReviewAssistanceKind } from "./lesson";

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
  key:
    | "input_received"
    | "context_prepared"
    | "authorized_resource_checked"
    | "runtime_started"
    | "domain_tool_running"
    | "domain_tool_completed"
    | "learning_reply_generated"
    | "replaced_by_newer_input";
  state: "completed" | "current";
  label: string;
};

export type TutorPublicProcess = {
  kind: "process";
  id: string;
  turn_id: string | null;
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
  turn_id: string | null;
  role: "learner" | "tutor";
  content: string;
  public_thinking_text: string;
  public_thinking_steps: string[];
  runtime_output: TutorRuntimeOutput | null;
  context_references: TutorContextReference[];
  in_reply_to_item_id: string | null;
  created_at: string | null;
};

export type TutorRequestOption = { value: string; label: string };

export type TutorRequestPresentation =
  | { type: "text"; field_key: string | null; minimum_length: number; maximum_length: number; multiline: boolean }
  | { type: "integer"; field_key: string; minimum: number; maximum: number; step: number; recommended: number | null; unit: string }
  | {
      type: "single_select";
      field_key: string;
      options: TutorRequestOption[];
      recommended: string | null;
      selection_scope: "explicit_shortlist" | "intent_shortlist" | "conflict_shortlist" | "full_catalog" | null;
      selection_reason_code: string | null;
      intent_policy_version: string | null;
    }
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
  public_thinking_text: string;
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
  public_thinking_text: string;
  presentation: Extract<TutorRequestPresentation, { type: "approval" }>;
  allowed_actions: ("approve" | "deny")[];
  answer_turn_id: string | null;
  created_at: string | null;
  resolved_at: string | null;
};

export type TutorInteractionRequestItem = TutorElicitationItem | TutorApprovalItem;
export type TutorHistoryError = {
  kind: "error";
  id: string;
  turn_id: string | null;
  code: string;
  message: string;
  recoverable: boolean;
  created_at: string | null;
};

export type TutorArtifactKind =
  | "exercise_workspace"
  | "browser_preview"
  | "test_result"
  | "knowledge_check"
  | "model_code_review"
  | "sql_workspace"
  | "demonstration"
  | "source_inspector";

export type TutorArtifactPurpose =
  | "exercise"
  | "demonstration"
  | "knowledge_check"
  | "remediation"
  | "transfer_check"
  | "code_review"
  | "sql_exploration"
  | "result";

export type TutorArtifactOwnerKind = "lesson_gate" | "review_item" | "teaching_practice" | "learning_item";
export type TutorArtifactState = "pending" | "ready" | "active" | "running" | "completed" | "failed" | "cancelled" | "superseded";
export type TutorArtifactActionKind = "request_hint" | "request_direct_answer" | "run" | "respond" | "complete_review" | "cancel" | "acknowledge_demo_event" | "complete_demo";
export type TutorArtifactDifficulty = "D1" | "D2" | "D3" | "D4" | "D5";
export type TutorArtifactOutcome = "passed" | "failed" | "timed_out" | "cancelled" | "unavailable" | "invalid";
export type TutorBranchResponseDisposition = "answer_and_refocus" | "offer_switch" | "confirmed_switch";

export type TutorArtifactOption = { value: string; label: string };

export type TutorArtifactExerciseWorkspacePresentation = {
  type: "exercise_workspace_v1";
  exercise_version_id: string;
  language_id: string;
  editor_mode: "code" | "sql" | "structured_answer";
  starter_content: string;
  starter_content_hash: string;
  editable: boolean;
  live_preview: boolean;
  runtime_profile_key: string | null;
};

export type TutorArtifactBrowserPreviewPresentation = {
  type: "browser_preview_v1";
  source_artifact_id: string;
  source_content_hash: string;
  experience_tier: "local_non_authoritative";
  interactive: boolean;
};

export type TutorArtifactTestResultPresentation = {
  type: "test_result_v1";
  attempt_id: string;
  status: "pending" | "terminal";
  outcome: TutorArtifactOutcome | null;
  passed_count: number;
  total_count: number;
  summary_markdown: string;
  result_hash: string | null;
};

export type SafeExecutionStatus =
  | "success"
  | "compile_error"
  | "runtime_error"
  | "timeout"
  | "cancelled"
  | "unsupported"
  | "unavailable"
  | "failed";

export type SafeExecutionLocation = {
  line: number;
  column: number | null;
  end_line: number | null;
  end_column: number | null;
};

export type SafeTestFeedbackV2 = {
  case_id: string;
  passed: boolean;
  visible: boolean;
  message: string;
  duration_ms: number;
  location: SafeExecutionLocation | null;
};

export type SafeTableResultCell = string | number | boolean | null;

export type SafeExecutionPresentation =
  | { kind: "none" }
  | { kind: "table_result_v1"; columns: string[]; rows: SafeTableResultCell[][] };

export type SafeExecutionResultV2 = {
  schema_version: "safe-execution-result-v2";
  status: SafeExecutionStatus;
  stdout: string;
  stderr: string;
  test_feedback: SafeTestFeedbackV2[];
  passed_test_count: number;
  total_test_count: number;
  duration_ms: number;
  diagnostic_code: string;
  presentation: SafeExecutionPresentation;
};

export type TutorArtifactKnowledgeCheckPresentation = {
  type: "knowledge_check_v1";
  response_kind: "single_select" | "multi_select" | "prediction" | "ordering" | "code_range" | "short_text";
  prompt_markdown: string;
  options: TutorArtifactOption[];
  minimum_selections: number;
  maximum_selections: number;
  maximum_text_length: number;
  hints?: { level: 1 | 2 | 3; label: "方向" | "概念" | "结构"; markdown: string }[];
  revealed_hint_levels?: (1 | 2 | 3)[];
  answer_locked?: boolean;
  outcome?: "correct" | "incorrect" | null;
  assistance_kind?: "independent" | "hinted" | "direct_answer" | "remediated" | null;
  evaluation_markdown?: string;
  response_receipt_id?: string | null;
  remediation_handle?: string | null;
  transfer_handle?: string | null;
};

export type TutorArtifactModelCodeReviewPresentationV1 = {
  type: "model_code_review_v1";
  exercise_version_id: string;
  language_id: string;
  source_code: string;
  source_code_hash: string;
  line_count: number;
  review_categories: string[];
};

export type ModelReviewErrorCategoryV2 =
  | "requirements_drift"
  | "fabricated_api"
  | "logic_boundary"
  | "contract_integration"
  | "async_lifecycle"
  | "security_trust"
  | "error_false_success"
  | "weak_testing";

export type ModelReviewDiffLineV2 = {
  line_key: string;
  kind: "context" | "added" | "removed";
  text: string;
  source_line: number | null;
  modified_line: number | null;
};

export type ModelReviewDiffHunkV2 = {
  hunk_id: string;
  header: string;
  source_start: number;
  source_count: number;
  modified_start: number;
  modified_count: number;
  lines: ModelReviewDiffLineV2[];
};

export type ModelReviewArtifactV2 = {
  schema_version: "model_code_review_artifact_v2";
  presentation_mode: "code" | "diff";
  language_id: string;
  runtime_label: string;
  source_code: string | null;
  modified_code: string;
  source_hash: string | null;
  modified_hash: string;
  diff_hash: string;
  line_count: number;
  hunks: ModelReviewDiffHunkV2[];
};

export type TutorArtifactModelCodeReviewPresentationV2 = {
  type: "model_code_review_v2";
  exercise_version_id: string;
  presentation_hash: string;
  review_target: ModelReviewArtifactV2;
  review_categories: ModelReviewErrorCategoryV2[];
  submission_locked: boolean;
  outcome: "passed" | "failed" | null;
  score: number | null;
  evaluation_markdown: string;
  review_receipt_id: string | null;
  result_hash: string | null;
  remediation_handle: string | null;
};

export type TutorArtifactModelCodeReviewPresentation =
  | TutorArtifactModelCodeReviewPresentationV1
  | TutorArtifactModelCodeReviewPresentationV2;

export type ModelReviewFindingV2 = {
  client_finding_id: string;
  hunk_id: string;
  side: "source" | "modified";
  start_line: number;
  end_line: number;
  category: ModelReviewErrorCategoryV2;
  severity: "info" | "low" | "medium" | "high" | "critical";
  explanation: string;
};

export type ModelCodeReviewSubmissionV2 = {
  schema_version: "model_code_review_submission_v2";
  presentation_hash: string;
  verdict: "correctness_issue" | "no_correctness_issue" | "improvement_only" | "uncertain";
  findings: ModelReviewFindingV2[];
};

export type TutorArtifactSqlWorkspacePresentationV1 = {
  type: "sql_workspace_v1";
  exercise_version_id: string;
  dialect: "sqlite";
  starter_query: string;
  starter_query_hash: string;
  schema_markdown: string;
  max_rows: number;
};

export type TutorArtifactSqlColumnV2 = {
  name: string;
  data_type: "INTEGER" | "REAL" | "TEXT";
  nullable: boolean;
  primary_key: boolean;
};

export type TutorArtifactSqlForeignKeyV2 = {
  column: string;
  references_table: string;
  references_column: string;
};

export type TutorArtifactSqlTableV2 = {
  name: string;
  columns: TutorArtifactSqlColumnV2[];
  foreign_keys: TutorArtifactSqlForeignKeyV2[];
};

export type TutorArtifactSqlWorkspacePresentationV2 = {
  type: "sql_workspace_v2";
  exercise_version_id: string;
  dialect: "sqlite";
  execution_tier: "teaching_local";
  starter_query: string;
  starter_query_hash: string;
  tables: TutorArtifactSqlTableV2[];
  max_rows: number;
  public_result: Extract<SafeExecutionPresentation, { kind: "table_result_v1" }> | null;
  public_result_query_hash: string | null;
  public_result_attempt_id: string | null;
};

export type TutorArtifactSqlWorkspacePresentation =
  | TutorArtifactSqlWorkspacePresentationV1
  | TutorArtifactSqlWorkspacePresentationV2;

export type TutorArtifactDemonstrationPresentation = {
  type: "demonstration_v1";
  demonstration_mode: "interactive" | "static";
  language_id: string | null;
  source_content: string;
  source_content_hash: string;
  expected_event_key: string | null;
  duration_seconds: number | null;
};

export type TutorArtifactDemonstrationEventV2 = {
  event_key: string;
  payload_json: Readonly<Record<string, unknown>>;
  payload_hash: string;
};

export type TutorArtifactDemonstrationStepV2 = {
  step_key: string;
  title: string;
  instruction_markdown: string;
  source_content: string;
  source_content_hash: string;
  duration_seconds: number | null;
};

export type TutorArtifactDemonstrationPresentationV2 = {
  type: "demonstration_v2";
  descriptor_version: "demonstration_descriptor_v1";
  demonstration_mode: "interactive" | "static";
  source_version: string;
  language_id: string;
  steps: TutorArtifactDemonstrationStepV2[];
  expected_event: TutorArtifactDemonstrationEventV2 | null;
  total_duration_seconds: number | null;
  completion_policy_version: "demonstration_completion_policy_v1";
};

export type TutorArtifactSourceInspectorPresentation = {
  type: "source_inspector_v1";
  document_id: string;
  document_content_hash: string;
  block_id: string;
  excerpt: string;
  citation_ids: string[];
};

export type TutorArtifactPresentation =
  | TutorArtifactExerciseWorkspacePresentation
  | TutorArtifactBrowserPreviewPresentation
  | TutorArtifactTestResultPresentation
  | TutorArtifactKnowledgeCheckPresentation
  | TutorArtifactModelCodeReviewPresentation
  | TutorArtifactSqlWorkspacePresentation
  | TutorArtifactDemonstrationPresentation
  | TutorArtifactDemonstrationPresentationV2
  | TutorArtifactSourceInspectorPresentation;

export type TutorArtifactSourceReference = {
  kind: "lesson_document" | "exercise_version" | "attempt_result" | "review_session" | "teaching_checkpoint" | "source_citation" | "artifact";
  reference_id: string;
  reference_version: number | null;
  content_hash: string | null;
  label: string;
};

export type TutorArtifactAttemptSummary = {
  attempt_id: string;
  attempt_type: "run" | "submit" | "diagnostic_submit" | "review_submit";
  status: "pending" | "terminal";
  outcome: TutorArtifactOutcome | null;
  score: number | null;
  result_hash: string | null;
  accepted_at: string;
  terminal_at: string | null;
};

export type TutorArtifactAttemptResultV1 = {
  outcome: TutorArtifactOutcome;
  score: number;
  safe_feedback: Readonly<Record<string, unknown>>;
  capability_scores: Readonly<Record<string, number>>;
  policy_version: string;
  result_hash: string;
  terminal_at: string;
};

export type TutorArtifactAttemptResultV2 = {
  outcome: TutorArtifactOutcome;
  score: number;
  execution_result: SafeExecutionResultV2 | null;
  capability_scores: Readonly<Record<string, number>>;
  policy_version: string;
  result_hash: string;
  terminal_at: string;
};

type TutorArtifactAttemptDetailBase = {
  artifact_id: string;
  artifact_version: number;
  conversation_id: string;
  learning_track_id: string;
  knowledge_key: string;
  teaching_session_id: string;
  attempt_id: string;
  attempt_type: "run" | "submit" | "diagnostic_submit" | "review_submit";
  exercise_version_id: string;
  submission_hash: string;
  independence: "independent" | "hinted" | "remediated";
  assistance_kind: "independent" | "hinted" | "validation_evidence_viewed" | "remediated";
  status: "pending" | "terminal";
  execution_job_state:
    | "pending"
    | "claimed"
    | "launch_reserved"
    | "running"
    | "completed"
    | "timed_out"
    | "cancelled"
    | "unavailable"
    | "launch_uncertain"
    | "failed"
    | null;
  accepted_at: string;
};

export type TutorArtifactAttemptDetailV1 = TutorArtifactAttemptDetailBase & {
  schema_version: "tutor_learning_artifact_attempt_v1";
  result: TutorArtifactAttemptResultV1 | null;
};

export type TutorArtifactAttemptDetailV2 = TutorArtifactAttemptDetailBase & {
  schema_version: "tutor_learning_artifact_attempt_v2";
  result: TutorArtifactAttemptResultV2 | null;
};

export type TutorArtifactAttemptDetail = TutorArtifactAttemptDetailV1 | TutorArtifactAttemptDetailV2;

export type TutorArtifactBranchSummary = {
  branch_id: string;
  state: "active" | "resolved";
  disposition: TutorBranchResponseDisposition | null;
  round_count: number;
  item_count: number;
  collapsed: boolean;
};

export type TutorPublicArtifactItem = {
  kind: "artifact";
  id: string;
  conversation_id: string;
  turn_id: string | null;
  learning_track_id: string;
  knowledge_key: string;
  teaching_session_id: string;
  checkpoint_id: string;
  artifact_version: 1;
  artifact_kind: TutorArtifactKind;
  purpose: TutorArtifactPurpose;
  owner_kind: TutorArtifactOwnerKind;
  owner_id: string;
  owner_version: number;
  state: TutorArtifactState;
  blocking: boolean;
  title: string;
  instruction_markdown: string;
  difficulty: TutorArtifactDifficulty | null;
  presentation: TutorArtifactPresentation;
  allowed_actions: TutorArtifactActionKind[];
  source_references: TutorArtifactSourceReference[];
  active_attempt: TutorArtifactAttemptSummary | null;
  branch_summary: TutorArtifactBranchSummary | null;
  version: number;
  created_at: string;
  updated_at: string;
  terminal_at: string | null;
};

export type TutorArtifactResponse =
  | { kind: "single_select"; value: string }
  | { kind: "multi_select"; values: string[] }
  | { kind: "prediction" | "short_text"; text: string }
  | { kind: "ordering"; values: string[] }
  | { kind: "code_range"; start_line: number; end_line: number; category: string; note: string };

export type TutorArtifactAction =
  | { action: "request_hint"; hint_level: number | null }
  | { action: "request_direct_answer" }
  | { action: "run"; submission: string }
  | { action: "respond"; response: TutorArtifactResponse }
  | { action: "complete_review"; review_submission: ModelCodeReviewSubmission | ModelCodeReviewSubmissionV2 }
  | { action: "cancel"; reason: "learner_cancelled" }
  | { action: "acknowledge_demo_event"; event_key: string; event_nonce: string }
  | {
      action: "complete_demo";
      evidence:
        | { kind: "interactive_event"; event_key: string; payload_json: Readonly<Record<string, unknown>>; payload_hash: string; preview_nonce: string; preview_generation: number; preview_sequence: number }
        | { kind: "visible_clock"; clock_session_id: string; visible_elapsed_ms: number; foreground: true; current: true; visible: true; render_ready: true };
    };

export type TutorArtifactActionResponse = {
  artifact: TutorPublicArtifactItem;
  artifact_event_id: string;
  artifact_event_sequence: number;
  idempotent_replayed: boolean;
};

export type TutorPublicBranchItemReference = {
  item_sequence: number;
  branch_round: number;
  item_kind: "message" | "process";
  item_id: string;
  turn_id: string;
  item_role: "learner" | "tutor" | "process";
};

export type TutorPublicBranchGroup = {
  schema_version: "tutor_conversation_branch_v1";
  branch_id: string;
  anchor_artifact_id: string;
  teaching_session_id: string;
  checkpoint_id: string;
  state: "active" | "resolved";
  disposition: TutorBranchResponseDisposition | null;
  round_count: number;
  item_count: number;
  collapsed: boolean;
  items: TutorPublicBranchItemReference[];
  created_at: string;
  resolved_at: string | null;
};

export type TutorHistoryItem = TutorHistoryMessage | TutorPublicProcess | TutorInteractionRequestItem | TutorHistoryError | TutorPublicArtifactItem;

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
  input_revision: number;
  retry_of_turn_id: string | null;
  retry_root_turn_id: string | null;
  completion_reason: TutorTurnCompletionReason | null;
  created_at: string | null;
  updated_at: string | null;
};

export type TutorActiveThinking = {
  turn_id: string;
  input_revision: number;
  generation: number;
  state: "active" | "complete";
  text: string;
  complete: boolean;
  last_event_sequence: number;
};

export type TutorRuntimeOutputItem = {
  item_id: string;
  text: string;
  state: "streaming" | "completed";
  last_sequence: number;
};

export type TutorRuntimeOutput = {
  output_version: "tutor_runtime_output_v1";
  input_revision: number;
  generation: number;
  reasoning_items: TutorRuntimeOutputItem[];
  final_answer_item: TutorRuntimeOutputItem | null;
};

export type TutorTurnOutputPayload =
  | {
      output_version: "tutor_public_thinking_stream_v1";
      input_revision: number;
      generation: number;
      operation: "append";
      chunk_sequence: number;
      text: string;
    }
  | {
      output_version: "tutor_public_thinking_stream_v1";
      input_revision: number;
      generation: number;
      operation: "reset" | "complete" | "discard";
      chunk_sequence: number;
    }
  | {
      output_version: "tutor_runtime_item_stream_v1";
      input_revision: number;
      generation: number;
      operation: "append" | "complete";
      chunk_sequence: number;
      item_id: string;
      channel: "reasoning" | "final_answer";
      text: string;
    }
  | {
      output_version: "tutor_runtime_item_stream_v1";
      input_revision: number;
      generation: number;
      operation: "reset" | "discard";
      chunk_sequence: number;
      item_id: string;
      channel: "reasoning" | "final_answer";
    };

export type TutorConversationSnapshotResponse = {
  snapshot_version:
    | "tutor_conversation_snapshot_v2"
    | "tutor_conversation_snapshot_v3"
    | "tutor_conversation_snapshot_v4"
    | "tutor_conversation_snapshot_v5";
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
  active_thinking: TutorActiveThinking | null;
  active_runtime_output: TutorRuntimeOutput | null;
  active_artifact: TutorPublicArtifactItem | null;
  branches: TutorPublicBranchGroup[];
  pending_requests: TutorInteractionRequestItem[];
  queue: TutorQueuedInput[];
  timeline: TutorHistoryItem[];
  next_cursor: string | null;
  has_more: boolean;
  stream_cursor: string;
  teaching_sessions: TeachingSessionGroupProjection[];
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

export type TeachingSessionMessageReferenceDraft = {
  kind: "teaching_session_message";
  learning_track_id: string;
  knowledge_key: string;
  teaching_session_id: string;
  message_id: string;
};

export type TutorContextReferenceDraft =
  | LessonSelectionReferenceDraft
  | ExerciseFeedbackReferenceDraft
  | ExecutionResultReferenceDraft
  | ReviewFeedbackReferenceDraft
  | TeachingSessionMessageReferenceDraft;

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

export type TeachingSessionMessageContextReference = TutorContextReferenceBase & {
  kind: "teaching_session_message";
  teaching_session_id: string;
  message_id: string;
  turn_id: string;
  role: "learner" | "tutor";
  message_summary: string;
  message_created_at: string | null;
};

export type TutorContextReference =
  | LessonSelectionContextReference
  | ExerciseFeedbackContextReference
  | ExecutionResultContextReference
  | ReviewFeedbackContextReference
  | TeachingSessionMessageContextReference;

export type TeachingSessionMode = "guided" | "free_reading";
export type TeachingSessionStatus = "active" | "paused" | "completed" | "blocked";
export type TeachingPauseReason = "soft_pause" | "evidence_pause" | "authority_pause" | "session_pause" | "completion_pause";
export type TeachingControlKey = "open_session" | "continue" | "return_focus" | "change_example" | "escalate_guided" | "switch_mode" | "pause" | "resume" | "enter_next_knowledge";

export type TeachingFocusProjection = {
  focus_id: string;
  focus_kind: "knowledge" | "lesson_block" | "question" | "prerequisite" | "feedback";
  summary: string;
  source_handles: string[];
};

export type TeachingCheckpointProjection = {
  checkpoint_id: string;
  session_version: number;
  objective: { objective_id: string; summary: string; source_handles: string[] };
  active_focus: TeachingFocusProjection | null;
  suspended_focuses: TeachingFocusProjection[];
  unresolved_questions: Array<{ question_id: string; summary: string; state: "open" | "answered" | "deferred"; source_message_id: string | null }>;
  covered_concepts: string[];
  evidence_cursors: Array<{ evidence_kind: "gate" | "review" | "progress" | "assignment"; source_id: string; source_version: number }>;
  pause_reason: TeachingPauseReason;
  recommended_action_key: string | null;
};

export type TeachingActionDescriptor = {
  key: string;
  label: string;
  emphasis: "primary" | "secondary" | "quiet";
  enabled: boolean;
  disabled_reason: string | null;
  target_kind: "teaching_control" | "navigation" | "artifact";
  target_id: string | null;
  expected_versions: Partial<Record<"session" | "track" | "progress" | "assignment", number>>;
};

export type TeachingActionShelf = {
  schema_version: "teaching_action_shelf_v1";
  teaching_session_id: string;
  session_version: number;
  checkpoint_id: string;
  state: "ready" | "runtime_active" | "blocking_request" | "completion" | "free_reading";
  primary_action: TeachingActionDescriptor | null;
  secondary_actions: TeachingActionDescriptor[];
  overflow_actions: TeachingActionDescriptor[];
};

export type TeachingSessionProjection = {
  session_id: string;
  track_id: string;
  track_version: number;
  conversation_id: string;
  knowledge_key: string;
  status: TeachingSessionStatus;
  mode: TeachingSessionMode;
  session_version: number;
  progress_version: number;
  assignment_id: string;
  assignment_version: number;
  document_id: string;
  checkpoint_id: string | null;
  paused_at: string | null;
  completed_at: string | null;
  last_activity_at: string | null;
  checkpoint?: TeachingCheckpointProjection;
  action_shelf?: TeachingActionShelf | null;
  allowed_actions?: string[];
};

export type TeachingSessionGroupProjection = TeachingSessionProjection & { turn_ids: string[] };
export type TeachingSessionListResponse = { items: TeachingSessionProjection[] };
export type TeachingSessionOpenResponse = { teaching_session: TeachingSessionProjection; created: boolean; pending_run: Record<string, unknown> | null; idempotent_replayed: boolean };
export type TeachingSessionActionResponse = {
  teaching_session: TeachingSessionProjection;
  next_teaching_session?: TeachingSessionProjection;
  transitioned?: true;
  created?: boolean;
  pending_run: Record<string, unknown> | null;
  idempotent_replayed: boolean;
};

export type LessonFollowState = "following" | "follow_paused";
export type LessonFollowTarget = {
  block_id: string;
  document_id: string;
  document_content_hash: string;
  label: string;
};
