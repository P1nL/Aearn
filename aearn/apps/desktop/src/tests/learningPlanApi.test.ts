import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmLearningPlanSession, toLearningTrackSummary } from "../api/learning";
import type { LearningPlanSession } from "../types";

const capturedTrackDetail = {
  track_id: "ebe28dbc-bc89-4e1b-93fd-b5cc9784f801",
  language_id: "sql",
  language_display_name: "SQL",
  goal_text: "完成一条 SQLite 单表查询入门路线：看懂表和列，用 SELECT 选择指定列，用 WHERE 按数值或文本条件过滤，用 ORDER BY 对结果排序，并能在课程页面亲自运行查询和检查结果。先不学 JOIN、事务和运维。",
  target_level: "beginner",
  status: "active",
  version: 1,
  active_revision_id: "302fcdd5-980d-4f62-a0c1-a317dc6c3e5b",
  active_plan_title: "sql beginner 学习计划",
  current_knowledge_key: "n1_1",
  current_knowledge_title: "确认 SQLite 执行环境与方言边界",
  progress: { total: 2, completed: 0, in_progress: 0, review_due: 0, percent: 0 },
  review_due_count: 0,
  execution_tier: "teaching_local",
  execution_disclosure: "Local teaching execution is available for controlled development or internal demonstration; it is not a public container-isolation claim.",
  last_learned_at: null,
  updated_at: "2026-09-21T14:47:44.269406+00:00",
  created_at: "2026-09-21T14:47:44.269406+00:00",
  archived_at: null,
};

const draftReadySession: LearningPlanSession = {
  session_id: "plan-session-1",
  conversation_id: "plan-conversation-1",
  status: "draft_ready",
  preferred_language_id: "sql",
  version: 7,
  current_draft: {
    draft_id: "plan-draft-1",
    draft_version: 2,
    content_hash: "a".repeat(64),
    profile: {
      language_id: "sql",
      goal_text: capturedTrackDetail.goal_text,
      target_level: "beginner",
      weekly_minutes: 120,
      experience_level: "new",
      teaching_preferences: ["examples_first", "concise_feedback"],
      pace_summary: "每次约20分钟，使用浏览器里的交互编辑器。",
      title: "sql beginner 学习计划",
    },
    plan: {
      title: "sql beginner 学习计划",
      target_level: "beginner",
      modules: [{
        module_key: "m1",
        title: "起步前：SQLite 环境与方言边界",
        description: "确认 SQLite 执行环境与方言边界。",
        order_index: 0,
        is_core: true,
        is_skippable: false,
        nodes: [{
          knowledge_key: "n1_1",
          title: "确认 SQLite 执行环境与方言边界",
          description: "确认浏览器中的 SQLite 执行环境。",
          order_index: 0,
          is_core: true,
          prerequisite_keys: [],
          required_capabilities: ["sql"],
        }],
      }],
    },
    sources: [{ source_id: "postgresql-sql-docs", display_name: "PostgreSQL SQL Documentation", trust_tier: "trusted_de_facto" }],
    generator_version: "learning-plan-draft-capability-v1",
    policy_version: "learning-plan-draft-policy-v1",
    created_at: "2026-09-21T14:46:05.932563+00:00",
  },
  confirmed_track_id: null,
  last_error: null,
  created_at: "2026-09-21T13:55:44.370476+00:00",
  updated_at: "2026-09-21T14:46:05.932563+00:00",
  confirmed_at: null,
  cancelled_at: null,
};

const confirmedSession = {
  ...draftReadySession,
  status: "confirmed" as const,
  version: 8,
  confirmed_track_id: capturedTrackDetail.track_id,
  updated_at: "2026-09-21T14:47:44.269406+00:00",
  confirmed_at: "2026-09-21T14:47:44.348318+00:00",
};

const capturedConfirmPayload = {
  session: confirmedSession,
  track: capturedTrackDetail,
  idempotent_replayed: false,
};

const confirmInput = {
  userId: "user-1",
  session: draftReadySession,
  clientActionId: "learning-plan-confirm:test",
};

function mockConfirmResponse(payload: unknown) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(payload)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("learning plan confirmation contract", () => {
  it("accepts the captured detail-shaped track while keeping the public summary parser exact", async () => {
    const fetchMock = mockConfirmResponse(capturedConfirmPayload);

    await expect(confirmLearningPlanSession(confirmInput)).resolves.toEqual({
      session: confirmedSession,
      track: capturedTrackDetail,
    });
    expect(toLearningTrackSummary(capturedTrackDetail)).toBeNull();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8001/api/learning-plan-sessions/plan-session-1/confirm");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "Idempotency-Key": "learning-plan-confirm:test" });
    expect(JSON.parse(String(init?.body))).toEqual({
      user_id: "user-1",
      client_action_id: "learning-plan-confirm:test",
      expected_session_version: 7,
      draft_id: "plan-draft-1",
      draft_version: 2,
      content_hash: "a".repeat(64),
    });
  });

  it.each([
    ["missing detail field", () => {
      const { created_at: _createdAt, ...track } = capturedTrackDetail;
      return { ...capturedConfirmPayload, track };
    }],
    ["unknown detail field", () => ({
      ...capturedConfirmPayload,
      track: { ...capturedTrackDetail, provider_body: "PRIVATE_MARKER" },
    })],
    ["missing replay marker", () => {
      const { idempotent_replayed: _replayed, ...payload } = capturedConfirmPayload;
      return payload;
    }],
    ["unknown top-level field", () => ({ ...capturedConfirmPayload, diagnostic_json: {} })],
  ])("rejects %s", async (_name, makePayload) => {
    mockConfirmResponse(makePayload());

    await expect(confirmLearningPlanSession(confirmInput)).rejects.toThrow(
      "Learning plan confirmation returned an invalid payload",
    );
  });
});