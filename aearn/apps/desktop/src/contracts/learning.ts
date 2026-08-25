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
