import type { ReactElement, ReactNode } from "react";

import type { TutorPublicArtifactItem } from "../../../types";

import { BrowserPreviewArtifact } from "./BrowserPreviewArtifact";
import { CodeEditorArtifact } from "./CodeEditorArtifact";
import { ExecutionResultArtifact } from "./ExecutionResultArtifact";
import { DemonstrationArtifact } from "./DemonstrationArtifact";
import { SafeMarkdown } from "./SafeMarkdown";
import { KnowledgeCheckArtifact } from "./KnowledgeCheckArtifact";
import { ModelCodeReviewArtifact } from "./ModelCodeReviewArtifact";
import { SqlWorkspaceArtifact } from "./SqlWorkspaceArtifact";
import type { TutorArtifactActionHandler, TutorArtifactAttemptLoader, TutorArtifactReturnToSource, TutorDocumentReferenceOpener } from "./artifactRendererTypes";
import type { ArtifactRendererUiState } from "./artifactUiState";

export type ArtifactRendererProps = {
  artifact: TutorPublicArtifactItem;
  uiState: ArtifactRendererUiState;
  onUiStateChange: (update: Partial<ArtifactRendererUiState>) => void;
  onAction?: TutorArtifactActionHandler;
  actionBusy?: boolean;
  loadAttempt?: TutorArtifactAttemptLoader;
  onReturnToSource?: TutorArtifactReturnToSource;
  onOpenDocumentReference?: TutorDocumentReferenceOpener;
};

export type ArtifactRenderer = (props: ArtifactRendererProps) => ReactElement;
export type ArtifactPresentationType = TutorPublicArtifactItem["presentation"]["type"];

const ARTIFACT_RENDERER_REGISTRY = {
  exercise_workspace_v1: ExerciseWorkspaceRenderer,
  browser_preview_v1: BrowserPreviewRenderer,
  test_result_v1: TestResultRenderer,
  knowledge_check_v1: KnowledgeCheckRenderer,
  model_code_review_v1: ModelCodeReviewPlaceholder,
  model_code_review_v2: ModelCodeReviewRenderer,
  sql_workspace_v1: SqlWorkspacePlaceholder,
  sql_workspace_v2: SqlWorkspaceRenderer,
  demonstration_v1: DemonstrationRenderer,
  demonstration_v2: DemonstrationRenderer,
  source_inspector_v1: SourceInspectorRenderer,
} satisfies Record<ArtifactPresentationType, ArtifactRenderer>;

export const ARTIFACT_PRESENTATION_TYPES = Object.freeze(Object.keys(ARTIFACT_RENDERER_REGISTRY) as ArtifactPresentationType[]);

export function artifactRendererFor(type: string): ArtifactRenderer | null {
  if (!Object.prototype.hasOwnProperty.call(ARTIFACT_RENDERER_REGISTRY, type)) return null;
  return ARTIFACT_RENDERER_REGISTRY[type as ArtifactPresentationType];
}

function ExerciseWorkspaceRenderer({ artifact, onAction, actionBusy }: ArtifactRendererProps) {
  const presentation = artifact.presentation;
  if (presentation.type !== "exercise_workspace_v1") return <ArtifactContractError />;
  return <CodeEditorArtifact artifact={artifact} onAction={onAction} actionBusy={actionBusy} />;
}

function BrowserPreviewRenderer({ artifact }: ArtifactRendererProps) {
  if (artifact.presentation.type !== "browser_preview_v1") return <ArtifactContractError />;
  return <BrowserPreviewArtifact artifact={artifact} />;
}

function TestResultRenderer({ artifact, loadAttempt, onReturnToSource }: ArtifactRendererProps) {
  if (artifact.presentation.type !== "test_result_v1") return <ArtifactContractError />;
  return <ExecutionResultArtifact artifact={artifact} loadAttempt={loadAttempt} onReturnToSource={onReturnToSource} />;
}

function KnowledgeCheckRenderer({ artifact, onAction, actionBusy }: ArtifactRendererProps) {
  if (artifact.presentation.type !== "knowledge_check_v1") return <ArtifactContractError />;
  return <KnowledgeCheckArtifact artifact={artifact} onAction={onAction} actionBusy={actionBusy} />;
}

function ModelCodeReviewRenderer({ artifact, onAction, actionBusy }: ArtifactRendererProps) {
  if (artifact.presentation.type !== "model_code_review_v2") return <ArtifactContractError />;
  return <ModelCodeReviewArtifact artifact={artifact} onAction={onAction} actionBusy={actionBusy} />;
}

function ModelCodeReviewPlaceholder({ artifact }: ArtifactRendererProps) {
  if (artifact.presentation.type !== "model_code_review_v1") return <ArtifactContractError />;
  const presentation = artifact.presentation;
  return <ArtifactPlaceholder label="代码审查"><span>{presentation.language_id} · {presentation.line_count} 行</span></ArtifactPlaceholder>;
}

function SqlWorkspaceRenderer({ artifact, onAction, actionBusy }: ArtifactRendererProps) {
  if (artifact.presentation.type !== "sql_workspace_v2") return <ArtifactContractError />;
  return <SqlWorkspaceArtifact artifact={artifact} onAction={onAction} actionBusy={actionBusy} />;
}

function SqlWorkspacePlaceholder({ artifact }: ArtifactRendererProps) {
  const presentation = artifact.presentation;
  if (presentation.type !== "sql_workspace_v1") return <ArtifactContractError />;
  return <ArtifactPlaceholder label="SQL 工作区"><span>{presentation.dialect} · 最多 {presentation.max_rows} 行</span></ArtifactPlaceholder>;
}

function DemonstrationRenderer({ artifact, onAction, actionBusy }: ArtifactRendererProps) {
  if (artifact.presentation.type !== "demonstration_v1" && artifact.presentation.type !== "demonstration_v2") return <ArtifactContractError />;
  return <DemonstrationArtifact artifact={artifact} onAction={onAction} actionBusy={actionBusy} />;
}

function SourceInspectorRenderer({ artifact, onOpenDocumentReference }: ArtifactRendererProps) {
  const presentation = artifact.presentation;
  if (presentation.type !== "source_inspector_v1") return <ArtifactContractError />;
  return <section className="artifact-source-inspector" aria-label="来源定位">
    <blockquote>{presentation.excerpt}</blockquote>
    <button
      className="tutor-compact-button"
      type="button"
      disabled={!onOpenDocumentReference}
      onClick={(event) => onOpenDocumentReference?.({
        knowledgeKey: artifact.knowledge_key,
        source: { kind: "artifact", artifact_id: artifact.id, artifact_version: artifact.version },
      }, event.currentTarget)}
    >查看来源文档</button>
  </section>;
}

function ArtifactPlaceholder({ label, children }: { label: string; children: ReactNode }) {
  return <section className="inline-artifact-placeholder" aria-label={label}>{children}</section>;
}

function ArtifactContractError() {
  return <div className="inline-artifact-contract-error" role="alert">ARTIFACT_PRESENTATION_CONTRACT_ERROR</div>;
}
