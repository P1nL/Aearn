import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { OnMount } from "@monaco-editor/react";

import type { TutorPublicArtifactItem } from "../../../types";
import { Button } from "../../../ui/dsh-derived";
import {
  markCodeArtifactRun,
  saveCodeArtifactViewState,
  updateCodeArtifactSource,
  useCodeArtifactDraft,
} from "./artifactCodeState";
import { isTerminalArtifact } from "./artifactUiState";
import { BrowserPreviewSurface } from "./BrowserPreviewArtifact";
import type { TutorArtifactActionHandler } from "./artifactRendererTypes";

const MonacoEditor = lazy(() => import("@monaco-editor/react").then((module) => ({ default: module.default })));

export function CodeEditorArtifact({
  artifact,
  onAction,
  actionBusy = false,
}: {
  artifact: TutorPublicArtifactItem;
  onAction?: TutorArtifactActionHandler;
  actionBusy?: boolean;
}) {
  const presentation = artifact.presentation;
  if (presentation.type !== "exercise_workspace_v1") {
    return <div className="inline-artifact-contract-error" role="alert">ARTIFACT_PRESENTATION_CONTRACT_ERROR</div>;
  }
  const draft = useCodeArtifactDraft(artifact);
  const [localRunPending, setLocalRunPending] = useState(false);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const disposablesRef = useRef<Array<{ dispose: () => void }>>([]);
  const readOnly = isTerminalArtifact(artifact) || !presentation.editable;
  const stale = draft.lastRunSource !== null
    ? draft.lastRunSource !== draft.source
    : artifact.active_attempt !== null;
  const canRun = artifact.allowed_actions.includes("run") && !readOnly && Boolean(onAction);
  const modelPath = `inmemory://aearn/${encodeURIComponent(artifact.conversation_id)}/${encodeURIComponent(artifact.id)}/${artifact.version}.${extensionFor(presentation.language_id)}`;

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !draft.viewState) return;
    const frame = window.requestAnimationFrame(() => {
      editor.restoreViewState(draft.viewState as Parameters<typeof editor.restoreViewState>[0]);
      editor.layout();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [modelPath]);

  useEffect(() => () => {
    for (const disposable of disposablesRef.current) disposable.dispose();
    disposablesRef.current = [];
    const editor = editorRef.current;
    if (editor) saveCodeArtifactViewState(artifact.conversation_id, artifact.id, editor.saveViewState());
  }, [artifact.conversation_id, artifact.id]);

  const handleMount: OnMount = (editor) => {
    editorRef.current = editor;
    if (draft.viewState) editor.restoreViewState(draft.viewState as Parameters<typeof editor.restoreViewState>[0]);
    editor.layout();
    disposablesRef.current.forEach((disposable) => disposable.dispose());
    disposablesRef.current = [
      editor.onDidChangeCursorPosition(() => saveCodeArtifactViewState(artifact.conversation_id, artifact.id, editor.saveViewState())),
      editor.onDidScrollChange(() => saveCodeArtifactViewState(artifact.conversation_id, artifact.id, editor.saveViewState())),
    ];
  };

  async function runLatestDraft() {
    if (!canRun || localRunPending || actionBusy || !onAction) return;
    const submission = draft.source;
    setLocalRunPending(true);
    try {
      const result = await onAction({
        artifact,
        action: "run",
        payload: { action: "run", submission },
      });
      if (result) markCodeArtifactRun(artifact.conversation_id, artifact.id, submission);
    } finally {
      setLocalRunPending(false);
    }
  }

  return <section className={`code-editor-artifact${readOnly ? " readonly" : ""}`} aria-label="代码练习">
    <div className={`code-editor-preview-split${presentation.live_preview ? " has-preview" : ""}`}>
      <section className="code-editor-pane" aria-label="代码编辑器">
        <header className="code-editor-toolbar"><div><strong>{displayLanguage(presentation.language_id)}</strong><span>单文件</span></div>{readOnly ? <span className="code-editor-readonly">只读</span> : null}</header>
        <div className="code-editor-monaco" data-model-path={modelPath}>
          <Suspense fallback={<div className="code-editor-loading" role="status">正在加载代码编辑器…</div>}>
            <MonacoEditor
              path={modelPath}
              value={draft.source}
              language={monacoLanguage(presentation.language_id)}
              theme="light"
              keepCurrentModel
              saveViewState
              onMount={handleMount}
              onChange={(value) => {
                if (!readOnly) updateCodeArtifactSource(artifact.conversation_id, artifact.id, value ?? "");
              }}
              options={{
                ariaLabel: "练习代码",
                readOnly,
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
      {presentation.live_preview ? <BrowserPreviewSurface
        artifactId={artifact.id}
        sourceArtifactId={artifact.id}
        sessionId={artifact.teaching_session_id}
        artifactVersion={artifact.version}
        languageId={presentation.language_id}
        source={draft.source}
        enabled
        ariaLabel="代码实时预览"
      /> : null}
    </div>
    <footer className="code-editor-footer">
      <div className="code-editor-state" aria-live="polite">
        {readOnly ? <span>工件已终态，代码保持只读。</span> : stale ? <span className="code-editor-stale" role="status">代码已修改，上次运行结果已过期</span> : <span>Preview 实时更新；只有点击运行才会发送代码。</span>}
      </div>
      {artifact.allowed_actions.includes("run") ? <Button variant="primary" busy={localRunPending || actionBusy} disabled={!canRun || localRunPending || actionBusy} onClick={() => void runLatestDraft()}>运行</Button> : null}
    </footer>
  </section>;
}

function monacoLanguage(languageId: string): string {
  return {
    js: "javascript",
    javascript: "javascript",
    ts: "typescript",
    typescript: "typescript",
    html_css: "html",
    html: "html",
    css: "css",
    python: "python",
    sql: "sql",
  }[languageId] ?? "plaintext";
}

function extensionFor(languageId: string): string {
  return { javascript: "js", js: "js", typescript: "ts", ts: "ts", html_css: "html", html: "html", css: "css", python: "py", sql: "sql" }[languageId] ?? "txt";
}

function displayLanguage(languageId: string): string {
  return { javascript: "JavaScript", js: "JavaScript", typescript: "TypeScript", ts: "TypeScript", html_css: "HTML / CSS / JS", html: "HTML", css: "CSS", python: "Python", sql: "SQL" }[languageId] ?? languageId;
}
