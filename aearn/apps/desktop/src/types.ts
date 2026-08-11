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

export type TutorContinuationKind = "approval" | "capability_result" | "external_result";

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
  display_state: "thinking" | "completed" | "superseded" | "unavailable";
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
  created_at: string | null;
};

export type TutorHistoryItem = TutorHistoryMessage | TutorPublicProcess;

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
  merged: boolean;
  input_replayed: boolean;
  idempotent_replayed: boolean;
  run: TutorRunState;
  process: TutorPublicProcess | null;
  replaced_run_id: string | null;
  replaced_process: TutorPublicProcess | null;
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
