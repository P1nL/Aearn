import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchLessonDocumentReference,
  toLessonDocumentReferenceResolution,
} from "../api/learning";

const trackId = "22222222-2222-4222-8222-222222222222";
const conversationId = "33333333-3333-4333-8333-333333333333";
const userId = "11111111-1111-4111-8111-111111111111";
const documentId = "55555555-5555-4555-8555-555555555555";
const documentHash = "a".repeat(64);

function fixture(status: "current" | "historical" = "current") {
  const assignment = {
    assignment_id: "44444444-4444-4444-8444-444444444444",
    document_id: documentId,
    assignment_version: 2,
    status: status === "current" ? "active" : "superseded",
    content_hash: documentHash,
  };
  return {
    schema_version: "lesson_document_reference_v1",
    source_kind: "lesson_block",
    source_id: documentId + ":concept",
    conversation_id: conversationId,
    learning_track_id: trackId,
    knowledge_key: "javascript.closure",
    reference_status: status,
    assignment,
    current_assignment: status === "current" ? assignment : {
      ...assignment,
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
      blocks: [{
        block_id: "concept",
        order_index: 0,
        citation_ids: ["cite_1234567890abcdef"],
        type: "concept",
        title: "保持变量",
        paragraphs: ["函数保持词法环境。"],
        coverage_keys: ["javascript.closure"],
      }],
      content_hash: documentHash,
    },
    sources: [{
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
      evidence_excerpt: "A closure bundles a function with its lexical environment.",
    }],
    target: {
      block_id: "concept",
      block_content_hash: "b".repeat(64),
      safe_excerpt: "保持变量 函数保持词法环境。",
      citation_ids: ["cite_1234567890abcdef"],
      selected_citation_id: "cite_1234567890abcdef",
    },
  };
}


afterEach(() => vi.unstubAllGlobals());

describe("LessonDocument reference API", () => {
  it("sends one exact source identity and parses the bounded document payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const source = {
      kind: "lesson_block" as const,
      document_id: documentId,
      document_content_hash: documentHash,
      assignment_version: 2,
      block_id: "concept",
      citation_id: "cite_1234567890abcdef",
    };
    const result = await fetchLessonDocumentReference({
      userId,
      trackId,
      conversationId,
      knowledgeKey: "javascript.closure",
      source,
    });

    expect(result.reference_status).toBe("current");
    expect(result.target.block_id).toBe("concept");
    expect(result.document.content_hash).toBe(documentHash);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/lesson-references/" + conversationId + "/resolve");
    expect(JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      user_id: userId,
      knowledge_key: "javascript.closure",
      source,
    });
  });

  it("rejects extra fields, unknown target citations, and current identity mismatch", () => {
    const extra = fixture() as Record<string, unknown>;
    extra.private_document = { raw: true };
    expect(toLessonDocumentReferenceResolution(extra)).toBeNull();

    const badCitation = fixture();
    badCitation.target.citation_ids = ["cite_deadbeefdeadbeef"];
    expect(toLessonDocumentReferenceResolution(badCitation)).toBeNull();

    const currentMismatch = fixture();
    currentMismatch.current_assignment = { ...currentMismatch.assignment, assignment_id: "different" };
    expect(toLessonDocumentReferenceResolution(currentMismatch)).toBeNull();
  });

  it("accepts an exact historical document while retaining the current assignment pointer", () => {
    const historical = toLessonDocumentReferenceResolution(fixture("historical"));
    expect(historical?.reference_status).toBe("historical");
    expect(historical?.assignment.status).toBe("superseded");
    expect(historical?.current_assignment?.status).toBe("active");
  });

  it("rejects a valid-looking response when it does not echo the exact requested source identity", async () => {
    const mismatched = fixture();
    mismatched.source_id = documentId + ":heading";
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(mismatched), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchLessonDocumentReference({
      userId,
      trackId,
      conversationId,
      knowledgeKey: "javascript.closure",
      source: {
        kind: "lesson_block",
        document_id: documentId,
        document_content_hash: documentHash,
        assignment_version: 2,
        block_id: "concept",
        citation_id: "cite_1234567890abcdef",
      },
    })).rejects.toThrow("invalid payload");
  });

});
