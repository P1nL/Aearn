import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { lessonPreparePayload, lessonRun, lessonScope, lessonUserId, readyLessonPayload } from "../../../tests/lessonDocumentFixtures";
import { LessonDocumentPage } from "../LessonDocumentPage";

const lessonUrl = `http://127.0.0.1:8001/api/learning-tracks/${lessonScope.track_id}/lessons/${lessonScope.knowledge_key}`;
const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });

function installFetch(reads: unknown[], prepareResponse: unknown = lessonPreparePayload("preparing")) {
  let readIndex = 0;
  const fetchMock = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === `${lessonUrl}?user_id=${lessonUserId}` && (!init?.method || init.method === "GET")) {
      const payload = reads[Math.min(readIndex, reads.length - 1)];
      readIndex += 1;
      return json(payload);
    }
    if (url === `${lessonUrl}/prepare` && init?.method === "POST") return json(prepareResponse, 202);
    if (url === `${lessonUrl}/gates?user_id=${lessonUserId}`) return json({
      track_id: lessonScope.track_id, knowledge_key: lessonScope.knowledge_key,
      track_version: 3, progress_version: 2, assignment_id: readyLessonPayload().assignment.assignment_id,
      assignment_version: 1, items: [],
    });
    throw new Error(`Unexpected fake Lesson request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, readCount: () => readIndex };
}

async function mountLesson() {
  let rendered: ReturnType<typeof render> | undefined;
  await act(async () => {
    rendered = render(<LessonDocumentPage userId={lessonUserId} trackId={lessonScope.track_id} knowledgeKey={lessonScope.knowledge_key} embedded />);
  });
  if (!rendered) throw new Error("Lesson test failed to mount");
  return rendered;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("LessonDocumentPage public recovery", () => {
  it("shows failed code/message and retries with server versions, polls, then renders eleven frozen blocks", async () => {
    const { fetchMock, readCount } = installFetch([
      { ...lessonScope, status: "failed", authoring_run: lessonRun("failed") },
      { ...lessonScope, status: "preparing", authoring_run: lessonRun("running") },
      readyLessonPayload(),
    ]);
    const { container } = await mountLesson();
    expect(screen.getByRole("heading", { name: "课程准备未完成" })).toBeInTheDocument();
    expect(screen.getByText("课程生成结果未通过结构校验。")).toBeInTheDocument();
    expect(screen.getByText("LESSON_DOCUMENT_INVALID")).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);

    await act(async () => fireEvent.click(screen.getByRole("button", { name: "重试准备" })));
    expect(screen.getByRole("heading", { name: "正在生成可追溯课程" })).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[0]).toBe(`${lessonUrl}/prepare`);
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      user_id: lessonUserId, expected_track_version: 3, expected_progress_version: 2,
      client_action_id: expect.stringMatching(/^lesson-prepare:/),
    });
    expect(post?.[1]?.headers).toMatchObject({ "Idempotency-Key": expect.stringMatching(/^lesson-prepare:/) });
    await act(async () => vi.advanceTimersByTimeAsync(1399));
    expect(readCount()).toBe(2);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(screen.getByRole("article", { name: "变量与基本数据类型" })).toBeInTheDocument();
    expect(container.querySelectorAll("[data-lesson-block-id]")).toHaveLength(11);
    expect(screen.getByRole("button", { name: "开始本课" })).toBeEnabled();
    expect(screen.getByText("Python 官方教程")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("LESSON_DOCUMENT_INVALID")).not.toBeInTheDocument();
    const terminalReads = readCount();
    await act(async () => vi.advanceTimersByTimeAsync(4200));
    expect(readCount()).toBe(terminalReads);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("prepares missing explicitly and accepts compact ready idempotent replay before rereading authority", async () => {
    const { fetchMock } = installFetch([{ ...lessonScope, status: "missing" }, readyLessonPayload()], lessonPreparePayload("ready", true));
    await mountLesson();
    expect(screen.getByRole("heading", { name: "课程尚未准备" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "准备课程" })));
    expect(screen.getByRole("article", { name: "变量与基本数据类型" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("accepts failed prepare replay and retains the explicit retry action", async () => {
    const failed = { ...lessonScope, status: "failed", authoring_run: lessonRun("failed") };
    const { fetchMock } = installFetch([failed], lessonPreparePayload("failed", true));
    await mountLesson();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "重试准备" })));
    expect(screen.getByText("LESSON_DOCUMENT_INVALID")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试准备" })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(4200));
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("cleans up preparing polling when unmounted", async () => {
    const { readCount } = installFetch([{ ...lessonScope, status: "preparing", authoring_run: lessonRun("pending") }]);
    const { unmount } = await mountLesson();
    await act(async () => vi.advanceTimersByTimeAsync(1400));
    expect(readCount()).toBe(2);
    unmount();
    await act(async () => vi.advanceTimersByTimeAsync(4200));
    expect(readCount()).toBe(2);
  });

  it("shows a safe contract error and never renders leaked diagnostics or a partial document", async () => {
    installFetch([{ ...readyLessonPayload(), diagnostic_json: { provider_body: "PRIVATE_MARKER" } }]);
    await mountLesson();
    expect(screen.getByRole("alert")).toHaveTextContent("LessonDocument API returned an invalid payload");
    expect(screen.getByRole("button", { name: "重新读取" })).toBeEnabled();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("PRIVATE_MARKER");
  });
});
