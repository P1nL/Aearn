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

export type TutorThreadTurnV2CutoverState = "idle" | "preparing" | "blocked" | "ready" | "enabled";

export type TutorThreadTurnV2Capability = {
  schema_version: "tutor_thread_turn_v2_capability_v1";
  cutover_version: "tutor_thread_turn_v2_global_v1";
  desktop_contract_version: "tutor_thread_turn_v2_desktop_v1";
  env_allowed: boolean;
  state: TutorThreadTurnV2CutoverState;
  generation: number;
  summary_hash: string | null;
  block_code: string | null;
  effective_enabled: boolean;
  counts: Record<string, boolean | number | string | Record<string, number>>;
  prepared_at: string | null;
  enabled_at: string | null;
  updated_at: string | null;
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


export class ApiRequestError extends Error {
  readonly apiError: ApiError;

  constructor(apiError: ApiError) {
    super(`${apiError.code}: ${apiError.message}`);
    this.apiError = apiError;
  }
}
