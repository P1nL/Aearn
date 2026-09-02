import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LessonAssignment, LessonDocument } from "../../../types";
import { LessonDocumentView } from "../lesson/LessonDocumentView";

const documentProjection: LessonDocument = {
  schema_version: "lesson_document_v1",
  title: "闭包基础",
  language_id: "javascript",
  knowledge_key: "javascript.closure",
  content_standard_version: "lesson-content-v1",
  coverage_keys: ["javascript.closure"],
  blocks: [
    { block_id: "closure-intro", order_index: 0, citation_ids: [], type: "heading", title: "闭包", subtitle: "从词法环境开始" },
    { block_id: "closure-example", order_index: 1, citation_ids: [], type: "concept", title: "保持变量", paragraphs: ["函数会保持对词法环境的引用。"], coverage_keys: ["javascript.closure"] },
  ],
  content_hash: "a".repeat(64),
};
const assignment: LessonAssignment = {
  assignment_id: "assignment-1", document_id: "document-1", assignment_version: 1, status: "active",
  content_hash: documentProjection.content_hash, started_at: null, activated_at: null, progress_status: "available", progress_version: 1,
};

describe("LessonDocumentView guided follow", () => {
  const scrollIntoView = vi.fn();

  beforeEach(() => {
    scrollIntoView.mockReset();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  });

  it("follows only an exact active document/hash/block target and pauses on learner interaction", async () => {
    const onPause = vi.fn();
    const onConflict = vi.fn();
    const { container } = render(<LessonDocumentView
      document={documentProjection}
      assignment={assignment}
      sources={[]}
      followEnabled
      followTarget={{ block_id: "closure-example", document_id: "document-1", document_content_hash: documentProjection.content_hash, label: "保持变量" }}
      onFollowPause={onPause}
      onFollowConflict={onConflict}
    />);

    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "start" }));
    expect(onConflict).toHaveBeenCalledWith(null);
    await new Promise((resolve) => globalThis.setTimeout(resolve, 20));
    fireEvent.pointerDown(container.querySelector('[data-lesson-block-id="closure-example"]')!);
    expect(onPause).toHaveBeenCalledTimes(1);
  });

  it("fails closed when the projected document hash is stale", async () => {
    const onConflict = vi.fn();
    render(<LessonDocumentView
      document={documentProjection}
      assignment={assignment}
      sources={[]}
      followEnabled
      followTarget={{ block_id: "closure-example", document_id: "document-1", document_content_hash: "b".repeat(64), label: "保持变量" }}
      onFollowConflict={onConflict}
    />);

    await waitFor(() => expect(onConflict).toHaveBeenCalledWith(expect.stringContaining("active frozen LessonDocument")));
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(screen.getByRole("article", { name: "闭包基础" })).toBeInTheDocument();
  });

  it("hands a citation to the drawer with the exact active document, version, block, hash, and trigger", async () => {
    const user = userEvent.setup();
    const onOpenDocumentReference = vi.fn();
    const citedDocument: LessonDocument = {
      ...documentProjection,
      blocks: documentProjection.blocks.map((block) => block.block_id === "closure-example"
        ? { ...block, citation_ids: ["cite_1234567890abcdef"] }
        : block),
    };
    render(<LessonDocumentView
      document={citedDocument}
      assignment={assignment}
      sources={[{
        citation_id: "cite_1234567890abcdef",
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
        evidence_excerpt: "A closure retains its lexical environment.",
      }]}
      onOpenDocumentReference={onOpenDocumentReference}
    />);

    const trigger = screen.getByRole("button", { name: "查看引用来源 1" });
    await user.click(trigger);
    expect(onOpenDocumentReference).toHaveBeenCalledWith({
      knowledgeKey: "javascript.closure",
      source: {
        kind: "lesson_block",
        document_id: "document-1",
        document_content_hash: documentProjection.content_hash,
        assignment_version: 1,
        block_id: "closure-example",
        citation_id: "cite_1234567890abcdef",
      },
    }, trigger);
    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});
