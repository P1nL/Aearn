import type { LearningTrackSummary } from "./learning";

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
