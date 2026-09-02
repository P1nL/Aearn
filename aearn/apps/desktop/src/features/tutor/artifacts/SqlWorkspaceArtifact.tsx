import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { OnMount } from "@monaco-editor/react";

import type { TutorPublicArtifactItem } from "../../../types";
import { Button } from "../../../ui/dsh-derived";
import type { TutorArtifactActionHandler } from "./artifactRendererTypes";
import {
  markSqlArtifactRun,
  saveSqlArtifactViewState,
  updateSqlArtifactQuery,
  useSqlArtifactDraft,
} from "./artifactSqlState";
import { isTerminalArtifact } from "./artifactUiState";
import { SafeTableResultGrid } from "./SafeTableResultGrid";

const MonacoEditor = lazy(() => import("@monaco-editor/react").then((module) => ({ default: module.default })));

export function SqlWorkspaceArtifact({
  artifact,
  onAction,
  actionBusy = false,
}: {
  artifact: TutorPublicArtifactItem;
  onAction?: TutorArtifactActionHandler;
  actionBusy?: boolean;
}) {
  const presentation = artifact.presentation;
  if (presentation.type !== "sql_workspace_v2") {
    return <div className="inline-artifact-contract-error" role="alert">ARTIFACT_PRESENTATION_CONTRACT_ERROR</div>;
  }
  const draft = useSqlArtifactDraft(artifact);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const disposablesRef = useRef<Array<{ dispose: () => void }>>([]);
  const copyResetTimerRef = useRef<number | null>(null);
  const [localRunPending, setLocalRunPending] = useState(false);
  const [copiedName, setCopiedName] = useState<string | null>(null);
  const terminal = isTerminalArtifact(artifact);
  const attemptPending = artifact.active_attempt?.status === "pending" || artifact.state === "running";
  const canRun = artifact.allowed_actions.includes("run") && !terminal && !attemptPending &&
    draft.query.trim().length > 0 && Boolean(onAction);
  const stale = draft.lastRunQuery !== null && draft.lastRunQuery !== draft.query;
  const modelPath = `inmemory://aearn/${encodeURIComponent(artifact.conversation_id)}/${encodeURIComponent(artifact.id)}/${artifact.version}.sql`;

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !draft.viewState) return;
    const frame = window.requestAnimationFrame(() => {
      editor.restoreViewState(draft.viewState as Parameters<typeof editor.restoreViewState>[0]);
      editor.layout();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [draft.viewState, modelPath]);

  useEffect(() => () => {
    for (const disposable of disposablesRef.current) disposable.dispose();
    disposablesRef.current = [];
    if (copyResetTimerRef.current !== null) window.clearTimeout(copyResetTimerRef.current);
    const editor = editorRef.current;
    if (editor) saveSqlArtifactViewState(artifact.conversation_id, artifact.id, editor.saveViewState());
  }, [artifact.conversation_id, artifact.id]);

  const handleMount: OnMount = (editor) => {
    editorRef.current = editor;
    if (draft.viewState) editor.restoreViewState(draft.viewState as Parameters<typeof editor.restoreViewState>[0]);
    editor.layout();
    disposablesRef.current.forEach((disposable) => disposable.dispose());
    disposablesRef.current = [
      editor.onDidChangeCursorPosition(() => saveSqlArtifactViewState(artifact.conversation_id, artifact.id, editor.saveViewState())),
      editor.onDidScrollChange(() => saveSqlArtifactViewState(artifact.conversation_id, artifact.id, editor.saveViewState())),
    ];
  };

  async function runLatestQuery() {
    if (!canRun || localRunPending || actionBusy || !onAction) return;
    const query = draft.query;
    setLocalRunPending(true);
    try {
      const result = await onAction({ artifact, action: "run", payload: { action: "run", submission: query } });
      if (result) markSqlArtifactRun(artifact.conversation_id, artifact.id, query);
    } finally {
      setLocalRunPending(false);
    }
  }

  async function copyName(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedName(value);
      if (copyResetTimerRef.current !== null) window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = window.setTimeout(() => {
        setCopiedName((current) => current === value ? null : current);
        copyResetTimerRef.current = null;
      }, 1_200);
    } catch {
      setCopiedName(null);
    }
  }

  return <section className={`sql-workspace-artifact${terminal ? " readonly" : ""}`} aria-label="SQL 学习工作区">
    <div className="sql-workspace-split">
      <section className="sql-editor-pane" aria-label="SQL 编辑器">
        <header className="code-editor-toolbar">
          <div><strong>SQLite</strong><span>单条只读查询</span></div>
          {terminal ? <span className="code-editor-readonly">只读</span> : null}
        </header>
        <div className="code-editor-monaco" data-model-path={modelPath}>
          <Suspense fallback={<div className="code-editor-loading" role="status">正在加载 SQL 编辑器…</div>}>
            <MonacoEditor
              path={modelPath}
              value={draft.query}
              language="sql"
              theme="light"
              keepCurrentModel
              saveViewState
              onMount={handleMount}
              onChange={(value) => {
                if (!terminal) updateSqlArtifactQuery(artifact.conversation_id, artifact.id, value ?? "");
              }}
              options={{
                ariaLabel: "SQL 查询",
                readOnly: terminal,
                automaticLayout: true,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                wordWrap: "on",
                fontSize: 13,
                lineHeight: 21,
                tabSize: 2,
                renderWhitespace: "selection",
                padding: { top: 10, bottom: 10 },
              }}
            />
          </Suspense>
        </div>
      </section>
      <section className="sql-schema-pane" aria-label="公开数据库结构">
        <header className="sql-schema-toolbar">
          <div><strong>Schema</strong><span>{presentation.tables.length} 张表</span></div>
          <span className="sql-copy-status" aria-live="polite">{copiedName ? `已复制 ${copiedName}` : ""}</span>
        </header>
        <div className="sql-schema-tree">
          {presentation.tables.map((table) => <details key={table.name} open>
            <summary>
              <span>{table.name}</span>
              <CopySqlNameButton value={table.name} onCopy={copyName} />
            </summary>
            <ul>
              {table.columns.map((column) => {
                const foreignKey = table.foreign_keys.find((item) => item.column === column.name) ?? null;
                const qualifiedName = `${table.name}.${column.name}`;
                return <li key={column.name}>
                  <div>
                    <code>{column.name}</code>
                    <span>{column.data_type}</span>
                    {column.primary_key ? <small>PK</small> : null}
                    {foreignKey ? <small>FK</small> : null}
                    {column.nullable ? <small>NULL</small> : null}
                  </div>
                  <CopySqlNameButton value={qualifiedName} onCopy={copyName} />
                  {foreignKey ? <p>→ {foreignKey.references_table}.{foreignKey.references_column}</p> : null}
                </li>;
              })}
            </ul>
          </details>)}
        </div>
      </section>
    </div>

    <footer className="sql-workspace-footer">
      <div className="code-editor-state" aria-live="polite">
        {terminal ? <span>工件已完成，查询保持只读。</span>
          : attemptPending ? <span role="status">正在运行公开查询并检查非公开数据…</span>
          : stale ? <span className="code-editor-stale" role="status">查询已修改，最近结果已过期</span>
          : <span>只有点击运行才会执行查询；不会自动运行。</span>}
      </div>
      {artifact.allowed_actions.includes("run") ? <Button
        variant="primary"
        busy={localRunPending || actionBusy || attemptPending}
        disabled={!canRun || localRunPending || actionBusy || attemptPending}
        onClick={() => void runLatestQuery()}
      >运行</Button> : null}
    </footer>

    <section className="sql-public-result" aria-label="最近一次公开查询结果">
      <header><strong>公开查询结果</strong><span>最多 {presentation.max_rows} 行</span></header>
      {presentation.public_result ? <SafeTableResultGrid
        columns={presentation.public_result.columns}
        rows={presentation.public_result.rows}
        ariaLabel="SQL 公开查询结果表格"
        className="sql-result-table-scroll"
      /> : <p>{attemptPending ? "查询运行中…" : "运行查询后在这里显示公开数据。"}</p>}
    </section>
  </section>;
}

function CopySqlNameButton({ value, onCopy }: { value: string; onCopy: (value: string) => Promise<void> }) {
  return <button
    type="button"
    className="sql-copy-name"
    aria-label={`复制 ${value}`}
    title={`复制 ${value}`}
    onMouseDown={(event) => event.preventDefault()}
    onClick={(event) => {
      event.stopPropagation();
      void onCopy(value);
    }}
  >复制</button>;
}
