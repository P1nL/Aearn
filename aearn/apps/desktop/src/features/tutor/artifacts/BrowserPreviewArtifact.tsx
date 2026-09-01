import { useRef } from "react";

import type { TutorPublicArtifactItem } from "../../../types";
import { Button } from "../../../ui/dsh-derived";
import { useCodeArtifactDraftById } from "./artifactCodeState";
import { useBrowserPreviewHost } from "./useBrowserPreviewHost";

export function BrowserPreviewArtifact({ artifact }: { artifact: TutorPublicArtifactItem }) {
  const presentation = artifact.presentation;
  if (presentation.type !== "browser_preview_v1") {
    return <div className="inline-artifact-contract-error" role="alert">ARTIFACT_PRESENTATION_CONTRACT_ERROR</div>;
  }
  const sourceDraft = useCodeArtifactDraftById(artifact.conversation_id, presentation.source_artifact_id);
  if (!sourceDraft) {
    return <section className="browser-preview-artifact unavailable" aria-label="浏览器预览">
      <PreviewUnavailable code="PREVIEW_SOURCE_NOT_READY" />
    </section>;
  }
  const sourceScopeMatches = sourceDraft.learningTrackId === artifact.learning_track_id
    && sourceDraft.knowledgeKey === artifact.knowledge_key
    && sourceDraft.teachingSessionId === artifact.teaching_session_id
    && sourceDraft.sourceContentHash === presentation.source_content_hash;
  if (!sourceScopeMatches) {
    return <section className="browser-preview-artifact unavailable" aria-label="浏览器预览">
      <PreviewUnavailable code="PREVIEW_SOURCE_SCOPE_MISMATCH" />
    </section>;
  }
  return <BrowserPreviewSurface
    artifactId={artifact.id}
    sourceArtifactId={presentation.source_artifact_id}
    sessionId={artifact.teaching_session_id}
    artifactVersion={artifact.version}
    languageId={sourceDraft.languageId}
    source={sourceDraft.source}
    enabled={presentation.interactive}
    ariaLabel="浏览器预览"
  />;
}

export function BrowserPreviewSurface({
  artifactId,
  sourceArtifactId,
  sessionId,
  artifactVersion,
  languageId,
  source,
  enabled,
  ariaLabel = "浏览器预览",
}: {
  artifactId: string;
  sourceArtifactId: string;
  sessionId: string;
  artifactVersion: number;
  languageId: string;
  source: string;
  enabled: boolean;
  ariaLabel?: string;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const preview = useBrowserPreviewHost({
    enabled,
    scope: { artifactId, sourceArtifactId, sessionId, artifactVersion, languageId },
    source,
    containerRef: viewportRef,
  });

  return <section className={`browser-preview-artifact status-${preview.status}`} aria-label={ariaLabel}>
    <header className="browser-preview-toolbar">
      <div><strong>Preview</strong><span>{previewStatusLabel(preview.status)}</span></div>
      <Button size="sm" variant="ghost" disabled={preview.status === "unavailable" || preview.status === "recreating"} onClick={preview.recreate}>重新加载</Button>
    </header>
    <div className="browser-preview-native-viewport" ref={viewportRef} data-preview-host-status={preview.status} aria-label="隔离预览画布">
      {preview.status === "unavailable" ? <PreviewUnavailable code="PREVIEW_HOST_UNAVAILABLE" /> : null}
      {preview.status === "creating" || preview.status === "recreating" ? <div className="browser-preview-status" role="status">正在启动隔离预览…</div> : null}
      {preview.status === "error" ? <PreviewUnavailable code={preview.errorCode ?? "PREVIEW_HOST_ERROR"} /> : null}
    </div>
    {preview.runtimeError ? <div className="browser-preview-runtime-error" role="alert"><strong>运行时错误</strong><span>{preview.runtimeError}</span></div> : null}
    {preview.consoleItems.length > 0 ? <details className="browser-preview-console">
      <summary>Console · {preview.consoleItems.length}</summary>
      <ol>{preview.consoleItems.map((item) => <li key={item.id} data-level={item.level}><span>{item.level}</span><code>{item.message}</code></li>)}</ol>
    </details> : null}
    {preview.interactionEventKey ? <span className="browser-preview-interaction" role="status">互动事件：{preview.interactionEventKey}</span> : null}
  </section>;
}

function PreviewUnavailable({ code }: { code: string }) {
  return <div className="browser-preview-unavailable" role="status"><strong>{code}</strong><span>隔离宿主不可用；不会回退到主页面执行代码。</span></div>;
}

function previewStatusLabel(status: ReturnType<typeof useBrowserPreviewHost>["status"]): string {
  return {
    unavailable: "不可用",
    creating: "启动中",
    ready: "实时",
    recreating: "正在重建",
    error: "不可用",
  }[status];
}
