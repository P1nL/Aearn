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
  created_at: string | null;
  updated_at: string | null;
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

export class ApiRequestError extends Error {
  readonly apiError: ApiError;

  constructor(apiError: ApiError) {
    super(`${apiError.code}: ${apiError.message}`);
    this.apiError = apiError;
  }
}
