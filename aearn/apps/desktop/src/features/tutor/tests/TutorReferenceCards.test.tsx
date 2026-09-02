import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { TutorContextReference } from "../../../types";
import { TutorReferenceCards } from "../TutorConversationParts";

const reference: TutorContextReference = {
  kind: "lesson_selection",
  reference_id: "88888888-8888-4888-8888-888888888888",
  schema_version: "tutor_context_reference_v1",
  learning_track_id: "22222222-2222-4222-8222-222222222222",
  knowledge_key: "javascript.closure",
  source_version: "lesson_document_v1",
  source_hash: "a".repeat(64),
  safe_payload_hash: "b".repeat(64),
  created_at: "2026-09-01T00:00:00Z",
  document_id: "55555555-5555-4555-8555-555555555555",
  document_content_hash: "c".repeat(64),
  content_standard_version: "lesson-content-v1",
  assignment_version: 2,
  block_id: "concept",
  start_offset: 0,
  end_offset: 10,
  safe_excerpt: "函数保持词法环境。",
};

describe("TutorReferenceCards", () => {
  it("opens lesson selections by exact persisted context-reference id and preserves the trigger", async () => {
    const user = userEvent.setup();
    const onOpenDocumentReference = vi.fn();
    render(<TutorReferenceCards references={[reference]} onOpenDocumentReference={onOpenDocumentReference} />);

    const trigger = screen.getByRole("button", { name: /课程选段/ });
    await user.click(trigger);
    expect(onOpenDocumentReference).toHaveBeenCalledWith({
      knowledgeKey: "javascript.closure",
      source: { kind: "context_reference", reference_id: reference.reference_id },
    }, trigger);
  });

  it("does not make non-document references or lesson selections without an opener interactive", () => {
    const { rerender } = render(<TutorReferenceCards references={[reference]} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("函数保持词法环境。")).toBeInTheDocument();

    rerender(<TutorReferenceCards references={[{
      ...reference,
      kind: "teaching_session_message",
      teaching_session_id: "99999999-9999-4999-8999-999999999999",
      message_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      turn_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      role: "tutor",
      message_summary: "历史解释",
      message_created_at: null,
    }]} onOpenDocumentReference={vi.fn()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
