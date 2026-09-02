import { useEffect } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TutorPublicArtifactItem } from "../../../types";
import { SqlWorkspaceArtifact } from "./SqlWorkspaceArtifact";
import { resetSqlArtifactDraftsForTests } from "./artifactSqlState";

const editorHarness = vi.hoisted(() => ({
  restoreViewState: vi.fn(),
  saveViewState: vi.fn(() => ({ cursor: 3, scrollTop: 12 })),
  layout: vi.fn(),
  focus: vi.fn(),
  setSelection: vi.fn(),
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
    id: "artifact-sql",
    conversation_id: "conversation-1",
    turn_id: "turn-1",
    learning_track_id: "track-1",
    knowledge_key: "sql.fundamentals",
    teaching_session_id: "session-1",
    checkpoint_id: "checkpoint-1",
    artifact_version: 1,
    artifact_kind: "sql_workspace",
    purpose: "sql_exploration",
    owner_kind: "learning_item",
    owner_id: "item-1",
    owner_version: 4,
    state: "active",
    blocking: true,
    title: "筛选 SQL 学习者",
    instruction_markdown: "查询 SQL 学习方向。",
    difficulty: "D2",
    presentation: {
      type: "sql_workspace_v2",
      exercise_version_id: "exercise-sql-1",
      dialect: "sqlite",
      execution_tier: "teaching_local",
      starter_query: "SELECT name FROM learners WHERE track = 'python' ORDER BY id;",
      starter_query_hash: "a".repeat(64),
      tables: [
        {
          name: "mentors",
          columns: [
            { name: "id", data_type: "INTEGER", nullable: false, primary_key: true },
            { name: "name", data_type: "TEXT", nullable: false, primary_key: false },
          ],
          foreign_keys: [],
        },
        {
          name: "learners",
          columns: [
            { name: "id", data_type: "INTEGER", nullable: false, primary_key: true },
            { name: "name", data_type: "TEXT", nullable: false, primary_key: false },
            { name: "track", data_type: "TEXT", nullable: false, primary_key: false },
            { name: "mentor_id", data_type: "INTEGER", nullable: true, primary_key: false },
          ],
          foreign_keys: [
            { column: "mentor_id", references_table: "mentors", references_column: "id" },
          ],
        },
      ],
      max_rows: 20,
      public_result: { kind: "table_result_v1", columns: ["name"], rows: [["Grace"], [null]] },
      public_result_query_hash: "b".repeat(64),
      public_result_attempt_id: "attempt-1",
    },
    allowed_actions: ["run", "cancel"],
    source_references: [],
    active_attempt: {
      attempt_id: "attempt-1",
      attempt_type: "run",
      status: "terminal",
      outcome: "failed",
      score: 0.5,
      result_hash: "c".repeat(64),
      accepted_at: "2026-09-02T08:00:00Z",
      terminal_at: "2026-09-02T08:00:01Z",
    },
    branch_summary: null,
    version: 3,
    created_at: "2026-09-02T08:00:00Z",
    updated_at: "2026-09-02T08:00:01Z",
    terminal_at: null,
    ...update,
  };
}

describe("SqlWorkspaceArtifact", () => {
  beforeEach(() => {
    resetSqlArtifactDraftsForTests();
    vi.clearAllMocks();
  });

  afterEach(() => cleanup());

  it("runs only the exact latest query and renders the bounded public result", async () => {
    const onAction = vi.fn().mockResolvedValue(artifact({ version: 4, state: "running" }));
    render(<SqlWorkspaceArtifact artifact={artifact()} onAction={onAction} />);

    const editor = await screen.findByRole("textbox", { name: "SQL 查询" });
    fireEvent.change(editor, { target: { value: "SELECT name FROM learners WHERE track = 'sql' ORDER BY id;" } });
    expect(onAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "运行" }));

    await waitFor(() => expect(onAction).toHaveBeenCalledTimes(1));
    expect(onAction.mock.calls[0]?.[0]).toMatchObject({
      artifact: { id: "artifact-sql", version: 3 },
      action: "run",
      payload: {
        action: "run",
        submission: "SELECT name FROM learners WHERE track = 'sql' ORDER BY id;",
      },
    });
    expect(screen.getByRole("columnheader", { name: "name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Grace" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "NULL" })).toBeInTheDocument();
  });

  it("copies table and qualified names without editing or focusing Monaco", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    render(<SqlWorkspaceArtifact artifact={artifact()} onAction={vi.fn()} />);
    const editor = await screen.findByRole("textbox", { name: "SQL 查询" });
    const original = (editor as HTMLTextAreaElement).value;
    const copy = screen.getByRole("button", { name: "复制 learners.mentor_id" });
    fireEvent.mouseDown(copy);
    await user.click(copy);

    expect(writeText).toHaveBeenCalledWith("learners.mentor_id");
    expect(editor).toHaveValue(original);
    expect(editorHarness.setSelection).not.toHaveBeenCalled();
    expect(editorHarness.focus).not.toHaveBeenCalled();
    expect(await screen.findByText("已复制 learners.mentor_id")).toBeInTheDocument();
    expect(screen.getByText("→ mentors.id")).toBeInTheDocument();
  });

  it("keeps terminal and pending workspaces non-runnable", async () => {
    const rendered = render(<SqlWorkspaceArtifact artifact={artifact({
      state: "running",
      active_attempt: {
        attempt_id: "attempt-pending",
        attempt_type: "run",
        status: "pending",
        outcome: null,
        score: null,
        result_hash: null,
        accepted_at: "2026-09-02T08:00:02Z",
        terminal_at: null,
      },
    })} onAction={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "运行" })).toBeDisabled();
    expect(screen.getByText("正在运行公开查询并检查非公开数据…")).toBeInTheDocument();

    rendered.rerender(<SqlWorkspaceArtifact artifact={artifact({
      state: "completed",
      allowed_actions: [],
      terminal_at: "2026-09-02T08:00:03Z",
    })} onAction={vi.fn()} />);
    expect(await screen.findByRole("textbox", { name: "SQL 查询" })).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "运行" })).not.toBeInTheDocument();
  });
});
