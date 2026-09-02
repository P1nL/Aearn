import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ fetchLessonDocumentReference: vi.fn() }));
vi.mock("../../../api", () => api);

import type { LessonDocumentReferenceOpenRequest, LessonDocumentReferenceResolution } from "../../../types";
import { LessonDocumentDrawer } from "../lesson/LessonDocumentDrawer";

const userId = "11111111-1111-4111-8111-111111111111";
const trackId = "22222222-2222-4222-8222-222222222222";
const conversationId = "33333333-3333-4333-8333-333333333333";
const documentId = "55555555-5555-4555-8555-555555555555";
const documentHash = "a".repeat(64);
const citationId = "cite_1234567890abcdef";
const scrollTo = vi.fn();
let narrow = false;
let reducedMotion = false;

const directRequest: LessonDocumentReferenceOpenRequest = {
  knowledgeKey: "javascript.closure",
  source: {
    kind: "lesson_block",
    document_id: documentId,
    document_content_hash: documentHash,
    assignment_version: 2,
    block_id: "concept",
    citation_id: citationId,
  },
};

function resolution(
  status: "current" | "historical" = "current",
  targetBlockId: "heading" | "concept" = "concept",
): LessonDocumentReferenceResolution {
  const assignment = {
    assignment_id: "44444444-4444-4444-8444-444444444444",
    document_id: documentId,
    assignment_version: 2,
    status: status === "current" ? "active" as const : "superseded" as const,
    content_hash: documentHash,
  };
  return {
    schema_version: "lesson_document_reference_v1",
    source_kind: "lesson_block",
    source_id: documentId + ":" + targetBlockId,
    conversation_id: conversationId,
    learning_track_id: trackId,
    knowledge_key: "javascript.closure",
    reference_status: status,
    assignment,
    current_assignment: status === "current" ? assignment : {
      assignment_id: "66666666-6666-4666-8666-666666666666",
      document_id: "77777777-7777-4777-8777-777777777777",
      assignment_version: 3,
      status: "active",
      content_hash: "c".repeat(64),
    },
    document: {
      schema_version: "lesson_document_v1",
      title: "闭包",
      language_id: "javascript",
      knowledge_key: "javascript.closure",
      content_standard_version: "lesson-content-v1",
      coverage_keys: ["javascript.closure"],
      blocks: [
        { block_id: "heading", order_index: 0, citation_ids: [], type: "heading", title: "闭包", subtitle: "词法环境" },
        { block_id: "concept", order_index: 1, citation_ids: [citationId], type: "concept", title: "保持变量", paragraphs: ["函数保持词法环境。"], coverage_keys: ["javascript.closure"] },
      ],
      content_hash: documentHash,
    },
    sources: [{
      citation_id: citationId,
      source_id: "mdn.closure",
      display_name: "MDN Closure",
      provider: "MDN",
      trust_tier: "official",
      source_type: "reference",
      source_version_label: "2026-08",
      source_version_kind: "fixed",
      canonical_url: "https://developer.mozilla.org/docs/Web/JavaScript/Closures",
      section_path: ["Closures"],
      fetched_at: "2026-08-30T00:00:00Z",
      snapshotted_at: "2026-08-30T00:00:01Z",
      evidence_excerpt: "A closure bundles a function with its lexical environment.",
    }],
    target: {
      block_id: targetBlockId,
      block_content_hash: (targetBlockId === "concept" ? "b" : "d").repeat(64),
      safe_excerpt: targetBlockId === "concept" ? "保持变量 函数保持词法环境。" : "闭包 词法环境",
      citation_ids: targetBlockId === "concept" ? [citationId] : [],
      selected_citation_id: targetBlockId === "concept" ? citationId : null,
    },
  };
}

class TestResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe = () => this.callback([], this as unknown as ResizeObserver);
  unobserve = vi.fn();
  disconnect = vi.fn();
}

beforeEach(() => {
  vi.clearAllMocks();
  narrow = false;
  reducedMotion = false;
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: query.includes("max-width") ? narrow : reducedMotion,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })));
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => window.setTimeout(() => callback(0), 0));
  vi.stubGlobal("cancelAnimationFrame", (id: number) => window.clearTimeout(id));
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
  Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: scrollTo });
  Object.defineProperty(HTMLElement.prototype, "offsetTop", {
    configurable: true,
    get() { return this.dataset.documentDrawerBlockId === "concept" ? 240 : 12; },
  });
  Object.defineProperty(HTMLElement.prototype, "offsetLeft", { configurable: true, get: () => 8 });
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 320 });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get: () => 148 });
});

describe("LessonDocumentDrawer", () => {
  it("loads the exact document, scrolls only its own panel, overlays the target, and closes only explicitly", async () => {
    api.fetchLessonDocumentReference.mockResolvedValue(resolution());
    const onClose = vi.fn();
    const rendered = render(<LessonDocumentDrawer
      userId={userId}
      trackId={trackId}
      conversationId={conversationId}
      request={directRequest}
      onClose={onClose}
    />);

    expect(await screen.findByRole("article", { name: "闭包" })).toBeInTheDocument();
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith({ top: 222, behavior: "smooth" }));
    const highlight = rendered.container.querySelector<HTMLElement>(".lesson-document-drawer-highlight");
    expect(highlight).toHaveStyle({ top: "240px", left: "8px", width: "320px", height: "148px" });
    expect(screen.getByText("A closure bundles a function with its lexical environment.")).toBeInTheDocument();
    expect(rendered.container.querySelectorAll("#document-drawer-lesson-sources-title")).toHaveLength(1);
    await waitFor(() => expect(screen.getByRole("button", { name: "收起" })).toHaveFocus());

    fireEvent.mouseDown(rendered.container.querySelector(".lesson-document-drawer-layer")!);
    fireEvent.click(rendered.container.querySelector(".lesson-document-drawer-layer")!);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("reuses the mounted drawer for a new exact target and shows the historical-version notice", async () => {
    reducedMotion = true;
    api.fetchLessonDocumentReference
      .mockResolvedValueOnce(resolution())
      .mockResolvedValueOnce(resolution("historical", "heading"));
    const rendered = render(<LessonDocumentDrawer
      userId={userId}
      trackId={trackId}
      conversationId={conversationId}
      request={directRequest}
      onClose={vi.fn()}
    />);
    await screen.findByText("保持变量");
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith({ top: 222, behavior: "auto" }));

    rendered.rerender(<LessonDocumentDrawer
      userId={userId}
      trackId={trackId}
      conversationId={conversationId}
      request={{
        knowledgeKey: "javascript.closure",
        source: {
          kind: "lesson_block",
          document_id: documentId,
          document_content_hash: documentHash,
          assignment_version: 2,
          block_id: "heading",
          citation_id: null,
        },
      }}
      onClose={vi.fn()}
    />);

    expect(await screen.findByText("内容已更新")).toBeInTheDocument();
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: "auto" }));
    expect(api.fetchLessonDocumentReference).toHaveBeenCalledTimes(2);
    expect(rendered.container.querySelector(".lesson-document-drawer-highlight")).toHaveStyle({ top: "12px" });
  });

  it("traps focus only in the narrow 88vw dialog and does not dismiss on the backdrop", async () => {
    narrow = true;
    api.fetchLessonDocumentReference.mockResolvedValue(resolution());
    const onClose = vi.fn();
    const rendered = render(<LessonDocumentDrawer
      userId={userId}
      trackId={trackId}
      conversationId={conversationId}
      request={directRequest}
      onClose={onClose}
    />);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const focusable = [...dialog.querySelectorAll<HTMLElement>('button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')];
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    first.focus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(first).toHaveFocus();

    fireEvent.click(rendered.container.querySelector(".lesson-document-drawer-layer")!);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "收起" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fails closed on resolver errors without searching rendered text for a fallback block", async () => {
    api.fetchLessonDocumentReference.mockRejectedValue(new Error("stale exact identity"));
    const rendered = render(<LessonDocumentDrawer
      userId={userId}
      trackId={trackId}
      conversationId={conversationId}
      request={directRequest}
      onClose={vi.fn()}
    />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(rendered.container.querySelector("[data-document-drawer-block-id]")).toBeNull();
    expect(rendered.container.querySelector(".lesson-document-drawer-highlight")).toBeNull();
  });

  it("aborts an in-flight retry before retargeting so an old document cannot overwrite the new source", async () => {
    let resolveRetry!: (value: LessonDocumentReferenceResolution) => void;
    const retry = new Promise<LessonDocumentReferenceResolution>((resolve) => { resolveRetry = resolve; });
    api.fetchLessonDocumentReference
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockReturnValueOnce(retry)
      .mockResolvedValueOnce(resolution("historical", "heading"));
    const rendered = render(<LessonDocumentDrawer
      userId={userId}
      trackId={trackId}
      conversationId={conversationId}
      request={directRequest}
      onClose={vi.fn()}
    />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    const retrySignal = api.fetchLessonDocumentReference.mock.calls[1]?.[0].signal as AbortSignal;
    expect(retrySignal.aborted).toBe(false);

    rendered.rerender(<LessonDocumentDrawer
      userId={userId}
      trackId={trackId}
      conversationId={conversationId}
      request={{
        knowledgeKey: "javascript.closure",
        source: {
          kind: "lesson_block",
          document_id: documentId,
          document_content_hash: documentHash,
          assignment_version: 2,
          block_id: "heading",
          citation_id: null,
        },
      }}
      onClose={vi.fn()}
    />);
    expect(await screen.findByText("内容已更新")).toBeInTheDocument();
    expect(retrySignal.aborted).toBe(true);
    resolveRetry(resolution());
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(screen.getByText("内容已更新")).toBeInTheDocument();
    expect(rendered.container.querySelector(".lesson-document-drawer-highlight")).toHaveStyle({ top: "12px" });
  });
});
