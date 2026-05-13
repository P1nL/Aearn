import type {
  ApiError,
  ApiHealth,
  CreatedPlanResponse,
  Language,
  LanguageCourse,
  LearningMode,
  PlanDraft,
  UserProfile,
} from "./types";

import { ApiRequestError } from "./types";

const API_BASE_URL = "http://127.0.0.1:8001";

export async function fetchApiHealth(signal?: AbortSignal): Promise<ApiHealth> {
  const payload = await requestJson(`${API_BASE_URL}/health`, { signal });
  if (!isApiHealth(payload)) {
    throw new Error("Health check returned an invalid payload");
  }
  return payload;
}

export async function fetchLanguageCourses(signal?: AbortSignal): Promise<LanguageCourse[]> {
  const payload = await requestJson(`${API_BASE_URL}/api/language-courses`, { signal });
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw new Error("Course catalog returned an invalid payload");
  }
  return payload.items.filter(isLanguageCourse);
}

export async function createUser(displayName: string, signal?: AbortSignal): Promise<UserProfile> {
  const payload = await requestJson(`${API_BASE_URL}/api/users`, {
    method: "POST",
    body: JSON.stringify({
      display_name: displayName,
      learning_style: "practice_first",
      teaching_preference: "step_by_step",
      encouragement_preference: "direct",
    }),
    signal,
  });
  if (!isRecord(payload) || !isUserProfile(payload.user)) {
    throw new Error("User API returned an invalid payload");
  }
  return payload.user;
}

export type GeneratePlanInput = {
  userId: string;
  mode: LearningMode;
  courseId: string;
  language: Language;
  goalText: string;
  materialTitle: string;
  materialContent: string;
};

export async function generatePlanDraft(input: GeneratePlanInput): Promise<PlanDraft> {
  const body =
    input.mode === "goal_based"
      ? {
          user_id: input.userId,
          mode: input.mode,
          goal_text: input.goalText,
          course_id: input.courseId,
          language: input.language,
          target_level: "beginner_to_intermediate",
        }
      : {
          user_id: input.userId,
          mode: input.mode,
          course_id: input.courseId,
          language: input.language,
          target_level: "beginner",
          materials: [
            {
              type: "text",
              title: input.materialTitle || "用户资料",
              content: input.materialContent,
            },
          ],
        };
  const payload = await requestJson(`${API_BASE_URL}/api/plans/generate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!isRecord(payload) || !isPlanDraft(payload.plan_draft)) {
    throw new Error("Plan generation returned an invalid payload");
  }
  return payload.plan_draft;
}

export async function confirmPlan(userId: string, planDraft: PlanDraft): Promise<CreatedPlanResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/plans`, {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      plan_draft: planDraft,
    }),
  });
  if (!isCreatedPlanResponse(payload)) {
    throw new Error("Plan confirmation returned an invalid payload");
  }
  return payload;
}

async function requestJson(url: string, init: RequestInit = {}): Promise<unknown> {
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Request-Id": `desktop-${Date.now()}`,
      ...init.headers,
    },
  });
  const payload: unknown = await response.json();
  if (!response.ok) {
    if (isApiErrorEnvelope(payload)) {
      throw new ApiRequestError(payload.error);
    }
    throw new Error(`API request failed with status ${response.status}`);
  }
  return payload;
}

function isApiHealth(payload: unknown): payload is ApiHealth {
  return isRecord(payload) && payload.status === "ok" && typeof payload.service === "string";
}

function isLanguageCourse(payload: unknown): payload is LanguageCourse {
  return (
    isRecord(payload) &&
    typeof payload.id === "string" &&
    typeof payload.title === "string" &&
    typeof payload.language === "string" &&
    isRecord(payload.runtime_profile) &&
    typeof payload.runtime_profile.runtime_tier === "string"
  );
}

function isUserProfile(payload: unknown): payload is UserProfile {
  return isRecord(payload) && typeof payload.id === "string" && typeof payload.display_name === "string";
}

function isPlanDraft(payload: unknown): payload is PlanDraft {
  return (
    isRecord(payload) &&
    typeof payload.draft_id === "string" &&
    typeof payload.user_id === "string" &&
    Array.isArray(payload.modules) &&
    isRecord(payload.runtime_boundary)
  );
}

function isCreatedPlanResponse(payload: unknown): payload is CreatedPlanResponse {
  return (
    isRecord(payload) &&
    isRecord(payload.LearningPlan) &&
    typeof payload.LearningPlan.id === "string" &&
    Array.isArray(payload.modules) &&
    Array.isArray(payload.knowledge_points) &&
    isRecord(payload.next_entry_point)
  );
}

function isApiErrorEnvelope(payload: unknown): payload is { error: ApiError } {
  return isRecord(payload) && isRecord(payload.error) && typeof payload.error.code === "string";
}

function isRecord(payload: unknown): payload is Record<string, unknown> {
  return typeof payload === "object" && payload !== null;
}
