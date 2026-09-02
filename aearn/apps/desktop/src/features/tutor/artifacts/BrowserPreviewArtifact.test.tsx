import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TutorPublicArtifactItem } from "../../../types";
import { BrowserPreviewArtifact, BrowserPreviewSurface } from "./BrowserPreviewArtifact";
import { CodeEditorArtifact } from "./CodeEditorArtifact";
import { resetCodeArtifactDraftsForTests } from "./artifactCodeState";

const previewHarness = vi.hoisted(() => ({
  input: null as null | {
    enabled: boolean;
    scope: { languageId: string; sourceArtifactId: string };
    source: string;
  },
  interactionEvent: null as null | {
    eventKey: string;
    payloadJson: Readonly<Record<string, unknown>>;
    nonce: string;
    generation: number;
    sequence: number;
  },
}));

vi.mock("@monaco-editor/react", () => ({
  default: (props: { value: string; options: { ariaLabel: string; readOnly: boolean } }) =>
    <textarea aria-label={props.options.ariaLabel} readOnly={props.options.readOnly} value={props.value} />,
}));

vi.mock("./useBrowserPreviewHost", () => ({
  useBrowserPreviewHost: (input: NonNullable<typeof previewHarness.input>) => {
    previewHarness.input = input;
    return {
      status: "unavailable" as const,
      errorCode: null,
      consoleItems: [],
      runtimeError: null,
      interactionEvent: previewHarness.interactionEvent,
      recreate: vi.fn(),
    };
  },
}));

function sourceArtifact(update: Partial<TutorPublicArtifactItem> = {}): TutorPublicArtifactItem {
  return {
    kind: "artifact",
    id: "artifact-source",
    conversation_id: "conversation-1",
    turn_id: "turn-1",
    learning_track_id: "track-1",
    knowledge_key: "javascript.dom",
    teaching_session_id: "session-1",
    checkpoint_id: "checkpoint-1",
    artifact_version: 1,
    artifact_kind: "exercise_workspace",
    purpose: "exercise",
    owner_kind: "lesson_gate",
    owner_id: "gate-1",
    owner_version: 1,
    state: "active",
    blocking: true,
    title: "Source",
    instruction_markdown: "Edit the source.",
    difficulty: "D2",
    presentation: {
      type: "exercise_workspace_v1",
      exercise_version_id: "exercise-1",
      language_id: "javascript",
      editor_mode: "code",
      starter_content: "console.log('safe');",
      starter_content_hash: "a".repeat(64),
      editable: true,
      live_preview: false,
      runtime_profile_key: "browser.preview",
    },
    allowed_actions: ["run"],
    source_references: [],
    active_attempt: null,
    branch_summary: null,
    version: 1,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    terminal_at: null,
    ...update,
  };
}

function previewArtifact(update: Partial<TutorPublicArtifactItem> = {}): TutorPublicArtifactItem {
  return {
    ...sourceArtifact(),
    id: "artifact-preview",
    artifact_kind: "browser_preview",
    purpose: "demonstration",
    title: "Preview",
    blocking: false,
    presentation: {
      type: "browser_preview_v1",
      source_artifact_id: "artifact-source",
      source_content_hash: "a".repeat(64),
      experience_tier: "local_non_authoritative",
      interactive: true,
    },
    allowed_actions: [],
    ...update,
  };
}

describe("BrowserPreviewArtifact source binding", () => {
  beforeEach(() => {
    resetCodeArtifactDraftsForTests();
    previewHarness.input = null;
    previewHarness.interactionEvent = null;
  });

  afterEach(() => cleanup());

  it("binds only the exact source Artifact scope/hash and preserves its language", () => {
    render(<>
      <CodeEditorArtifact artifact={sourceArtifact()} />
      <BrowserPreviewArtifact artifact={previewArtifact()} />
    </>);

    expect(previewHarness.input).toMatchObject({
      enabled: true,
      scope: { languageId: "javascript", sourceArtifactId: "artifact-source" },
      source: "console.log('safe');",
    });
    expect(screen.getByText("PREVIEW_HOST_UNAVAILABLE")).toBeInTheDocument();
  });

  it("fails closed when the preview source hash or TeachingSession scope mismatches", () => {
    const rendered = render(<>
      <CodeEditorArtifact artifact={sourceArtifact()} />
      <BrowserPreviewArtifact artifact={previewArtifact({
        presentation: {
          type: "browser_preview_v1",
          source_artifact_id: "artifact-source",
          source_content_hash: "b".repeat(64),
          experience_tier: "local_non_authoritative",
          interactive: true,
        },
      })} />
    </>);

    expect(screen.getByText("PREVIEW_SOURCE_SCOPE_MISMATCH")).toBeInTheDocument();
    expect(previewHarness.input).toBeNull();

    rendered.rerender(<>
      <CodeEditorArtifact artifact={sourceArtifact()} />
      <BrowserPreviewArtifact artifact={previewArtifact({ teaching_session_id: "session-2" })} />
    </>);
    expect(screen.getByText("PREVIEW_SOURCE_SCOPE_MISMATCH")).toBeInTheDocument();
    expect(previewHarness.input).toBeNull();
  });

  it("forwards each accepted Preview event once even if the parent callback changes", async () => {
    previewHarness.interactionEvent = {
      eventKey: "demo.click.completed",
      payloadJson: { count: 1 },
      nonce: "a".repeat(64),
      generation: 1,
      sequence: 1,
    };
    const first = vi.fn();
    const rendered = render(<BrowserPreviewSurface
      artifactId="artifact-preview"
      sourceArtifactId="artifact-source"
      sessionId="session-1"
      artifactVersion={1}
      languageId="javascript"
      source="console.log('safe');"
      enabled
      onInteractionEvent={first}
    />);
    await waitFor(() => expect(first).toHaveBeenCalledTimes(1));

    const second = vi.fn();
    rendered.rerender(<BrowserPreviewSurface
      artifactId="artifact-preview"
      sourceArtifactId="artifact-source"
      sessionId="session-1"
      artifactVersion={1}
      languageId="javascript"
      source="console.log('safe');"
      enabled
      onInteractionEvent={second}
    />);
    expect(second).not.toHaveBeenCalled();

    previewHarness.interactionEvent = {
      eventKey: "demo.click.completed",
      payloadJson: { count: 1 },
      nonce: "a".repeat(64),
      generation: 1,
      sequence: 2,
    };
    rendered.rerender(<BrowserPreviewSurface
      artifactId="artifact-preview"
      sourceArtifactId="artifact-source"
      sessionId="session-1"
      artifactVersion={1}
      languageId="javascript"
      source="console.log('safe');"
      enabled
      onInteractionEvent={second}
    />);
    await waitFor(() => expect(second).toHaveBeenCalledTimes(1));
  });
});