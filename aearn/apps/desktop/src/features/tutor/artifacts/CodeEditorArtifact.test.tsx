import { useEffect } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TutorPublicArtifactItem } from "../../../types";
import { CodeEditorArtifact } from "./CodeEditorArtifact";
import { resetCodeArtifactDraftsForTests } from "./artifactCodeState";

const editorHarness = vi.hoisted(() => ({
  restoreViewState: vi.fn(),
  saveViewState: vi.fn(() => ({ cursor: 2, scrollTop: 10 })),
  layout: vi.fn(),
  focus: vi.fn(),
  cursorListener: null as (() => void) | null,
  scrollListener: null as (() => void) | null,
}));

vi.mock("@monaco-editor/react", () => ({
  default: (props: {
    value: string;
    path: string;
    options: { ariaLabel: string; readOnly: boolean };
    onMount?: (editor: unknown) => void;
    onChange?: (value: string) => void;
  }) => {
    useEffect(() => {
      props.onMount?.({
        ...editorHarness,
        onDidChangeCursorPosition: (listener: () => void) => {
          editorHarness.cursorListener = listener;
          return { dispose: vi.fn() };
        },
        onDidScrollChange: (listener: () => void) => {
          editorHarness.scrollListener = listener;
          return { dispose: vi.fn() };
        },
      });
    }, []);
    return <textarea
      aria-label={props.options.ariaLabel}
      data-model-path={props.path}
      readOnly={props.options.readOnly}
      value={props.value}
      onChange={(event) => props.onChange?.(event.currentTarget.value)}
    />;
  },
}));

function artifact(update: Partial<TutorPublicArtifactItem> = {}): TutorPublicArtifactItem {
  return {
    kind: "artifact",
    id: "artifact-editor",
    conversation_id: "conversation-1",
    turn_id: "turn-1",
    learning_track_id: "track-1",
    knowledge_key: "dom.events",
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
    title: "DOM 事件练习",
    instruction_markdown: "完成按钮事件。",
    difficulty: "D2",
    presentation: {
      type: "exercise_workspace_v1",
      exercise_version_id: "exercise-1",
      language_id: "html_css",
      editor_mode: "code",
      starter_content: "<button>Start</button>",
      starter_content_hash: "a".repeat(64),
      editable: true,
      live_preview: false,
      runtime_profile_key: "browser.preview",
    },
    allowed_actions: ["run"],
    source_references: [],
    active_attempt: {
      attempt_id: "attempt-1",
      attempt_type: "run",
      status: "terminal",
      outcome: "failed",
      score: 0,
      result_hash: "b".repeat(64),
      accepted_at: "2026-09-01T00:00:00Z",
      terminal_at: "2026-09-01T00:00:01Z",
    },
    branch_summary: null,
    version: 1,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:01Z",
    terminal_at: null,
    ...update,
  };
}

describe("CodeEditorArtifact", () => {
  beforeEach(() => {
    resetCodeArtifactDraftsForTests();
    vi.clearAllMocks();
    editorHarness.cursorListener = null;
    editorHarness.scrollListener = null;
  });

  afterEach(() => cleanup());

  it("sends the exact latest draft only on explicit Run and marks later edits stale", async () => {
    const onAction = vi.fn().mockResolvedValue(artifact({ version: 2, state: "running" }));
    render(<CodeEditorArtifact artifact={artifact()} onAction={onAction} />);
    const editor = await screen.findByRole("textbox", { name: "练习代码" });
    expect(screen.getByText("代码已修改，上次运行结果已过期")).toBeInTheDocument();
    fireEvent.change(editor, { target: { value: "<button data-aearn-event=\"ok\">Run</button>" } });
    expect(screen.getByText("代码已修改，上次运行结果已过期")).toBeInTheDocument();
    expect(onAction).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "运行" }));
    await waitFor(() => expect(onAction).toHaveBeenCalledTimes(1));
    expect(onAction.mock.calls[0]?.[0]).toMatchObject({
      artifact: { id: "artifact-editor", version: 1 },
      action: "run",
      payload: { action: "run", submission: "<button data-aearn-event=\"ok\">Run</button>" },
    });
    await waitFor(() => expect(screen.queryByText("代码已修改，上次运行结果已过期")).not.toBeInTheDocument());

    fireEvent.change(editor, { target: { value: "<button data-aearn-event=\"ok\">Run</button>\n<!-- changed -->" } });
    expect(screen.getByText("代码已修改，上次运行结果已过期")).toBeInTheDocument();
  });

  it("preserves the process-local draft across authoritative Artifact versions and never focuses Monaco", async () => {
    const rendered = render(<CodeEditorArtifact artifact={artifact({ active_attempt: null })} />);
    const editor = await screen.findByRole("textbox", { name: "练习代码" });
    fireEvent.change(editor, { target: { value: "const preserved = true;" } });
    expect(editor).toHaveAttribute("data-model-path", expect.stringContaining("/1.html"));
    act(() => editorHarness.cursorListener?.());

    const next = artifact({
      version: 2,
      active_attempt: null,
      presentation: {
        ...(artifact().presentation as Extract<TutorPublicArtifactItem["presentation"], { type: "exercise_workspace_v1" }>),
        starter_content: "server replacement must not overwrite local draft",
      },
    });
    rendered.rerender(<CodeEditorArtifact artifact={next} />);
    expect(await screen.findByRole("textbox", { name: "练习代码" })).toHaveValue("const preserved = true;");
    expect(screen.getByRole("textbox", { name: "练习代码" })).toHaveAttribute("data-model-path", expect.stringContaining("/2.html"));
    await waitFor(() => expect(editorHarness.restoreViewState).toHaveBeenCalledWith({ cursor: 2, scrollTop: 10 }));
    expect(editorHarness.focus).not.toHaveBeenCalled();
  });

  it("keeps terminal Artifacts read-only and denies Run even if a malformed caller leaves the action present", async () => {
    render(<CodeEditorArtifact artifact={artifact({ state: "completed", terminal_at: "2026-09-01T00:00:02Z" })} onAction={vi.fn()} />);
    expect(await screen.findByRole("textbox", { name: "练习代码" })).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "运行" })).toBeDisabled();
    expect(screen.getByText("工件已终态，代码保持只读。")).toBeInTheDocument();
  });
});
