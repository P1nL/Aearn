import { useEffect, useRef, useState } from "react";

import type { TutorPublicArtifactItem } from "../../../types";
import { Button } from "../../../ui/dsh-derived";
import { artifactRendererFor } from "./ArtifactRendererRegistry";
import { SafeMarkdown } from "./SafeMarkdown";
import type { TutorArtifactActionHandler, TutorArtifactActionRequest, TutorArtifactAttemptLoader, TutorArtifactReturnToSource, TutorDocumentReferenceOpener } from "./artifactRendererTypes";
import {
  artifactUiStateKey,
  isTerminalArtifact,
  loadArtifactDetailCached,
  readArtifactUiState,
  writeArtifactUiState,
  type ArtifactRendererUiState,
} from "./artifactUiState";

export type { TutorArtifactActionHandler, TutorArtifactActionRequest } from "./artifactRendererTypes";
export type TutorArtifactAction = TutorPublicArtifactItem["allowed_actions"][number];

export type InlineArtifactMessageProps = {
  artifact: TutorPublicArtifactItem;
  autoReveal?: boolean;
  terminalCollapseMarker?: string | null;
  onAction?: TutorArtifactActionHandler;
  actionBusy?: boolean;
  loadDetail?: (artifact: TutorPublicArtifactItem) => Promise<TutorPublicArtifactItem>;
  loadAttempt?: TutorArtifactAttemptLoader;
  onReturnToSource?: TutorArtifactReturnToSource;
  onOpenDocumentReference?: TutorDocumentReferenceOpener;
};

const ACTION_LABELS: Record<TutorArtifactAction, string> = {
  request_hint: "查看提示",
  request_direct_answer: "查看答案",
  run: "运行",
  respond: "作答",
  complete_review: "完成审查",
  cancel: "取消",
  acknowledge_demo_event: "我已完成互动",
  complete_demo: "完成演示",
};

const STATE_LABELS: Record<TutorPublicArtifactItem["state"], string> = {
  pending: "准备中",
  ready: "已就绪",
  active: "进行中",
  running: "运行中",
  completed: "已完成",
  failed: "未完成",
  cancelled: "已取消",
  superseded: "已替换",
};

export function InlineArtifactMessage({
  artifact,
  autoReveal = false,
  terminalCollapseMarker = null,
  onAction,
  actionBusy = false,
  loadDetail,
  loadAttempt,
  onReturnToSource,
  onOpenDocumentReference,
}: InlineArtifactMessageProps) {
  const terminal = isTerminalArtifact(artifact);
  const hasSeenNonTerminalRef = useRef(!terminal);
  if (!terminal) hasSeenNonTerminalRef.current = true;
  const lazyDetailRequired = terminal && !hasSeenNonTerminalRef.current && Boolean(loadDetail);
  const [uiState, setUiState] = useState<ArtifactRendererUiState>(() => readArtifactUiState(
    artifact,
    autoReveal || !terminal,
  ));
  const [detailState, setDetailState] = useState<
    | { status: "ready"; artifact: TutorPublicArtifactItem }
    | { status: "loading" | "error"; artifact: null }
  >(() => lazyDetailRequired ? { status: "loading", artifact: null } : { status: "ready", artifact });
  const shellRef = useRef<HTMLElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const scrolledAutoRevealKeyRef = useRef<string | null>(null);
  const bodyId = `inline-artifact-body-${artifact.id}`;
  const cacheKey = artifactUiStateKey(artifact);
  const autoRevealScrollKey = autoReveal ? `${artifact.conversation_id}:${artifact.id}` : null;
  const detailStatus = lazyDetailRequired ? detailState.status : "ready";
  const renderedArtifact = lazyDetailRequired && detailState.status === "ready" ? detailState.artifact : artifact;
  const renderer = artifactRendererFor(renderedArtifact.presentation.type);
  const rendererOwnsResultSummary = renderedArtifact.presentation.type === "test_result_v1"
    && renderedArtifact.presentation.status === "terminal";
  const rendererOwnedActions = renderedArtifact.presentation.type === "exercise_workspace_v1"
    ? new Set<TutorArtifactAction>(["run"])
    : renderedArtifact.presentation.type === "sql_workspace_v2"
      ? new Set<TutorArtifactAction>(["run"])
    : renderedArtifact.presentation.type === "knowledge_check_v1"
      ? new Set<TutorArtifactAction>(["request_hint", "request_direct_answer", "respond"])
    : renderedArtifact.presentation.type === "model_code_review_v2"
      ? new Set<TutorArtifactAction>(["complete_review"])
    : renderedArtifact.presentation.type === "demonstration_v2"
      ? new Set<TutorArtifactAction>(["complete_demo", "acknowledge_demo_event"])
      : new Set<TutorArtifactAction>();
  const renderedActions = artifact.allowed_actions.filter((action) => !rendererOwnedActions.has(action));

  useEffect(() => {
    let next = readArtifactUiState(artifact, autoReveal || !terminal);
    if (autoReveal && !next.expanded) next = writeArtifactUiState(artifact, { expanded: true });
    setUiState(next);
  }, [artifact, autoReveal, cacheKey, terminal]);
  useEffect(() => {
    if (!lazyDetailRequired || !loadDetail) {
      setDetailState({ status: "ready", artifact });
      return;
    }
    if (!uiState.expanded) {
      setDetailState({ status: "loading", artifact: null });
      return;
    }
    let active = true;
    setDetailState({ status: "loading", artifact: null });
    void loadArtifactDetailCached(artifact, loadDetail).then((detail) => {
      if (active) setDetailState({ status: "ready", artifact: detail });
    }).catch(() => {
      if (active) setDetailState({ status: "error", artifact: null });
    });
    return () => { active = false; };
  }, [cacheKey, lazyDetailRequired, loadDetail, uiState.expanded]);

  useEffect(() => {
    if (!autoRevealScrollKey) {
      scrolledAutoRevealKeyRef.current = null;
      return;
    }
    if (!shellRef.current || scrolledAutoRevealKeyRef.current === autoRevealScrollKey) return;
    scrolledAutoRevealKeyRef.current = autoRevealScrollKey;
    const reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    shellRef.current.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  }, [autoRevealScrollKey]);

  useEffect(() => {
    if (!terminal || !terminalCollapseMarker || uiState.terminalCollapseMarker === terminalCollapseMarker) return;
    const next = writeArtifactUiState(artifact, {
      expanded: false,
      terminalCollapseMarker,
    });
    setUiState(next);
  }, [artifact, terminal, terminalCollapseMarker, uiState.terminalCollapseMarker]);

  useEffect(() => {
    if (!uiState.expanded || !bodyRef.current) return;
    bodyRef.current.scrollTop = uiState.scrollTop;
  }, [cacheKey, uiState.expanded]);

  function updateUiState(update: Partial<ArtifactRendererUiState>) {
    setUiState(writeArtifactUiState(artifact, update));
  }

  function toggleExpanded() {
    updateUiState({ expanded: !uiState.expanded });
  }

  return <article
    className={`inline-artifact-message state-${artifact.state}${renderer ? "" : " contract-error"}`}
    ref={shellRef}
    data-artifact-id={artifact.id}
    data-artifact-version={artifact.version}
    data-presentation={artifact.presentation.type}
  >
    <header className="inline-artifact-header">
      <button type="button" className="inline-artifact-toggle" aria-expanded={uiState.expanded} aria-controls={bodyId} onClick={toggleExpanded}>
        <span className="inline-artifact-heading"><strong>{artifact.title}</strong><small>{STATE_LABELS[artifact.state]}</small></span>
        <span className="inline-artifact-chevron" aria-hidden="true">⌄</span>
      </button>
      {artifact.difficulty ? <span className="inline-artifact-difficulty" aria-label={`难度 ${artifact.difficulty}`}>{formatDifficulty(artifact.difficulty)}</span> : null}
    </header>

    {uiState.expanded ? <div
      className="inline-artifact-body"
      id={bodyId}
      ref={bodyRef}
      aria-busy={detailStatus === "loading" || undefined}
      onScroll={(event) => updateUiState({ scrollTop: event.currentTarget.scrollTop })}
    >
      {!rendererOwnsResultSummary
        ? <SafeMarkdown markdown={artifact.instruction_markdown} surface="artifact" className="inline-artifact-instruction" />
        : null}
      {detailStatus === "loading"
        ? <div className="inline-artifact-detail-status" role="status">正在加载工件内容…</div>
        : detailStatus === "error"
          ? <div className="inline-artifact-contract-error" role="alert"><strong>ARTIFACT_DETAIL_CONTRACT_ERROR</strong><span>工件内容暂不可用</span></div>
          : renderer
            ? renderer({
                artifact: renderedArtifact,
                uiState,
                onUiStateChange: updateUiState,
                onAction,
                actionBusy,
                loadAttempt,
                onReturnToSource,
                onOpenDocumentReference,
              })
            : <div className="inline-artifact-contract-error" role="alert"><strong>ARTIFACT_PRESENTATION_CONTRACT_ERROR</strong><span>展示类型不可用</span></div>}
      {renderedArtifact.source_references.length > 0 ? <ArtifactSourceReferences artifact={renderedArtifact} /> : null}
      {terminal ? <ArtifactTerminalSummary artifact={artifact} /> : null}
      {renderer && renderedActions.length > 0 ? <div className="inline-artifact-actions" aria-label="工件操作">
        {renderedActions.map((action) => {
          const label = ACTION_LABELS[action];
          if (!label) return null;
          return <Button key={action} variant={action === "run" || action === "respond" || action === "complete_review" ? "primary" : "outline"} busy={actionBusy} disabled={!onAction || actionBusy} onClick={() => onAction?.({ artifact, action })}>{label}</Button>;
        })}
      </div> : null}
    </div> : null}
  </article>;
}

function ArtifactSourceReferences({ artifact }: { artifact: TutorPublicArtifactItem }) {
  return <div className="artifact-source-reference-chips" aria-label="工件来源引用">
    {artifact.source_references.map((reference) => <span
      key={[reference.kind, reference.reference_id, reference.reference_version, reference.content_hash].join(":")}
      data-kind={reference.kind}
      title={reference.label}
    ><span aria-hidden="true">§</span><strong>{reference.label}</strong></span>)}
  </div>;
}

function ArtifactTerminalSummary({ artifact }: { artifact: TutorPublicArtifactItem }) {
  const presentation = artifact.presentation;
  const summary = presentation.type === "test_result_v1" ? presentation.summary_markdown : "";
  if (!summary) return null;
  return <section className="inline-artifact-terminal-summary" aria-label="工件终态摘要">
    <SafeMarkdown markdown={summary} surface="artifact" />
  </section>;
}

function formatDifficulty(value: NonNullable<TutorPublicArtifactItem["difficulty"]>): string {
  return `D(${value.slice(1)})`;
}
