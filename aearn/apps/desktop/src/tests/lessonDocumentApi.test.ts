import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchLessonDocument, prepareLessonDocument, toLessonDocumentState, toLessonPrepareResponse } from "../api/learning";
import { lessonPreparePayload, lessonRun, lessonScope, lessonUserId, readyLessonPayload } from "./lessonDocumentFixtures";

afterEach(() => vi.unstubAllGlobals());

describe("LessonDocument exact public state", () => {
  it("accepts missing, including the server projection of a cancelled run without private lineage", () => {
    expect(toLessonDocumentState({ ...lessonScope, status: "missing" })).toEqual({
      ...lessonScope, status: "missing", assignment: null, document: null, sources: [], update: null, authoring_run: null,
    });
    expect(toLessonDocumentState({ ...lessonScope, status: "missing", authoring_run: lessonRun("cancelled") })).toBeNull();
  });

  it.each(["pending", "claimed", "running"] as const)("accepts preparing %s", (state) => {
    const run = lessonRun(state);
    expect(toLessonDocumentState({ ...lessonScope, status: "preparing", authoring_run: run })).toMatchObject({ status: "preparing", authoring_run: run, document: null });
  });

  it("preserves learner-safe failed code and message", () => {
    expect(toLessonDocumentState({ ...lessonScope, status: "failed", authoring_run: lessonRun("failed") })).toMatchObject({
      status: "failed", authoring_run: { failure_code: "LESSON_DOCUMENT_INVALID", failure_message: "课程生成结果未通过结构校验。" },
    });
  });

  it("accepts the eleven-block Python ready shape with all registered kinds and frozen sources", () => {
    const payload = readyLessonPayload();
    const result = toLessonDocumentState(payload);
    expect(result).toEqual({ ...payload, authoring_run: null });
    expect(result?.document?.blocks).toHaveLength(11);
    expect(new Set(result?.document?.blocks.map((block) => block.type)).size).toBe(10);
  });

  it.each([
    ["missing source", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, sources: [] })],
    ["duplicate source citation", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, sources: [...p.sources, p.sources[0]] })],
    ["duplicate block citation", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, document: { ...p.document, blocks: p.document.blocks.map((b, i) => i === 2 ? { ...b, citation_ids: [p.sources[0].citation_id, p.sources[0].citation_id] } : b) } })],
    ["duplicate order", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, document: { ...p.document, blocks: p.document.blocks.map((b, i) => i === 1 ? { ...b, order_index: 0 } : b) } })],
    ["non-continuous order", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, document: { ...p.document, blocks: p.document.blocks.map((b, i) => i === 1 ? { ...b, order_index: 12 } : b) } })],
    ["duplicate block ID", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, document: { ...p.document, blocks: p.document.blocks.map((b) => ({ ...b, block_id: "same" })) } })],
    ["unknown block", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, document: { ...p.document, blocks: [{ ...p.document.blocks[0], type: "markdown" }] } })],
    ["extra block field", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, document: { ...p.document, blocks: p.document.blocks.map((b) => ({ ...b, provider_body: "PRIVATE_MARKER" })) } })],
    ["credentialed source", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, sources: p.sources.map((s) => ({ ...s, canonical_url: "https://user:secret@example.test/" })) })],
    ["non-HTTP source", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, sources: p.sources.map((s) => ({ ...s, canonical_url: "javascript:alert(1)" })) })],
    ["invalid assignment", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, assignment: { ...p.assignment, status: "published" } })],
    ["unknown status", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, status: "cancelled" })],
    ["private diagnostic", (p: ReturnType<typeof readyLessonPayload>) => ({ ...p, diagnostic_json: { prompt: "PRIVATE_MARKER" } })],
  ])("rejects %s without weakening the unknown boundary", (_name, mutate) => {
    expect(toLessonDocumentState(mutate(readyLessonPayload()))).toBeNull();
  });

  it("rejects failed runs with unknown state, missing fields or private diagnostics", () => {
    const payload = { ...lessonScope, status: "failed", authoring_run: lessonRun("failed") };
    expect(toLessonDocumentState({ ...payload, authoring_run: { ...payload.authoring_run, state: "repairing" } })).toBeNull();
    const { failure_code: _code, ...missingCode } = payload.authoring_run;
    expect(toLessonDocumentState({ ...payload, authoring_run: missingCode })).toBeNull();
    expect(toLessonDocumentState({ ...payload, authoring_run: { ...payload.authoring_run, diagnostic_json: { prompt: "PRIVATE_MARKER" } } })).toBeNull();
  });
});

describe("Lesson prepare compact replay", () => {
  it("accepts cancelled same-key replay as compact missing without dispatch lineage", () => {
    const payload = { ...lessonPreparePayload("ready", true), status: "missing" };
    expect(toLessonPrepareResponse(payload)).toEqual(payload);
  });
  it.each(["preparing", "failed", "ready"] as const)("accepts %s replay and fresh response", (status) => {
    for (const replayed of [true, false]) {
      const payload = lessonPreparePayload(status, replayed);
      expect(toLessonPrepareResponse(payload)).toEqual(payload);
    }
  });

  it("rejects full ready read payload, internal dispatch and diagnostic fields", () => {
    expect(toLessonPrepareResponse({ ...readyLessonPayload(), idempotent_replayed: true })).toBeNull();
    expect(toLessonPrepareResponse({ ...lessonPreparePayload("ready", true), should_dispatch: false })).toBeNull();
    expect(toLessonPrepareResponse({ ...lessonPreparePayload("failed", true), authoring_run: { ...lessonRun("failed"), diagnostic_json: {} } })).toBeNull();
    const { idempotent_replayed: _replayed, ...missingReplay } = lessonPreparePayload("ready", true);
    expect(toLessonPrepareResponse(missingReplay)).toBeNull();
  });

  it("uses the exact prepare request and parses ready replay through the HTTP boundary", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(lessonPreparePayload("ready", true))));
    vi.stubGlobal("fetch", fetchMock);
    await expect(prepareLessonDocument({
      userId: lessonUserId, trackId: lessonScope.track_id, knowledgeKey: lessonScope.knowledge_key,
      expectedTrackVersion: 3, expectedProgressVersion: 2, clientActionId: "lesson-prepare:test",
    })).resolves.toEqual(lessonPreparePayload("ready", true));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`http://127.0.0.1:8001/api/learning-tracks/${lessonScope.track_id}/lessons/${lessonScope.knowledge_key}/prepare`);
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "Idempotency-Key": "lesson-prepare:test" });
    expect(JSON.parse(String(init?.body))).toEqual({ user_id: lessonUserId, client_action_id: "lesson-prepare:test", expected_track_version: 3, expected_progress_version: 2 });
  });

  it("does not include malformed payload content in public contract errors", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify({ ...readyLessonPayload(), diagnostic_json: "PRIVATE_MARKER" }))));
    await expect(fetchLessonDocument(lessonUserId, lessonScope.track_id, lessonScope.knowledge_key)).rejects.toThrow("LessonDocument API returned an invalid payload");
  });
});
