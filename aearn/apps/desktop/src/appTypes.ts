import type { ApiHealth, EnvironmentDoctorReport, LearningSessionResponse, LocalUserDataSummary, LocalUserListItem } from "./types";
import type { Language } from "./types";

export type ApiHealthState =
  | { status: "loading" }
  | { status: "online"; data: ApiHealth }
  | { status: "offline"; message: string };

export type EnvironmentDoctorState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: EnvironmentDoctorReport }
  | { status: "error"; message: string };

export type LocalUsersState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; items: LocalUserListItem[] }
  | { status: "error"; message: string };

export type UserDataSummaryState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: LocalUserDataSummary }
  | { status: "error"; message: string };

export type AsyncActionState =
  | { status: "idle" }
  | { status: "loading"; label: string }
  | { status: "error"; code: string; message: string; recoverable: boolean };

export type SessionState =
  | { status: "idle" }
  | { status: "loading"; knowledgePointId: string }
  | { status: "ready"; data: LearningSessionResponse }
  | { status: "error"; knowledgePointId: string | null; message: string };

export type ExerciseActionKind =
  | "run_preview"
  | "run_tests"
  | "submit"
  | "hint"
  | "explain_error"
  | "check_explanation";

export type ExerciseRunMode = "preview" | "visible_tests";
export type WorkbenchState = "pristine" | "dirty" | "running" | "submitted" | "unsupported";

export type AppRoute = "onboarding" | "home" | "review" | "notes" | "settings" | "cutover" | "tutor";
export type SettingsKey =
  | "appearance"
  | "models"
  | "learning"
  | "review"
  | "notifications"
  | "privacy"
  | "diagnostics";
export type NavGroupKey = "learn" | "review" | "notes" | "notes-python" | "notes-javascript" | "notes-sql";

export type ToolCallStatus = "pending" | "running" | "done" | "error";

export type ConversationToolCall = {
  id: string;
  name: string;
  args: unknown;
  argsBuffer: string;
  status: ToolCallStatus;
};

export type ConversationAttachment =
  | {
      type: "review_exercise";
      sessionId: string;
      exerciseId: string;
      knowledgePointId: string;
      title: string;
    };

export type ConversationMessage = {
  id: string;
  speaker: "agent" | "user";
  text: string;
  label?: string;
  presentation?: "bubble" | "attachment";
  status?: "streaming" | "error" | "done";
  statusText?: string;
  toolCalls?: ConversationToolCall[];
  attachment?: ConversationAttachment;
};

export type SettingsPanel = {
  title: string;
  meta: string;
  cards: [string, string][];
};

export type DraftModuleCard = {
  id: string;
  title: string;
  description: string;
  tag: string;
  tagClass: string;
};

export type LearnNavItem = {
  id: string;
  title: string;
  active: boolean;
};

export type RouteCard = {
  id: string;
  index: number;
  title: string;
  body: string;
  active: boolean;
  knowledgePointId: string;
};

export type ReviewCard = {
  title: string;
  body: string;
};

export type NoteContext = {
  knowledgePointId: string;
  knowledgePointTitle: string;
  source: "learning" | "review" | "notes";
  sessionId?: string;
  attemptId?: string;
  language?: Language | null;
};
