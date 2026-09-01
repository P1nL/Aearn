import type { ReactElement, ReactNode } from "react";

import type { TutorPublicArtifactItem } from "../../../types";

import { ExecutionResultArtifact } from "./ExecutionResultArtifact";
import { SafeMarkdown } from "./SafeMarkdown";
import type { TutorArtifactAttemptLoader, TutorArtifactReturnToSource } from "./artifactRendererTypes";
import type { ArtifactRendererUiState } from "./artifactUiState";

export type ArtifactRendererProps = {
  artifact: TutorPublicArtifactItem;
  uiState: ArtifactRendererUiState;
  onUiStateChange: (update: Partial<ArtifactRendererUiState>) => void;
  loadAttempt?: TutorArtifactAttemptLoader;
  onReturnToSource?: TutorArtifactReturnToSource;
};

export type ArtifactRenderer = (props: ArtifactRendererProps) => ReactElement;
export type ArtifactPresentationType = TutorPublicArtifactItem["presentation"]["type"];

const ARTIFACT_RENDERER_REGISTRY = {
  exercise_workspace_v1: ExerciseWorkspacePlaceholder,
  browser_preview_v1: BrowserPreviewPlaceholder,
  test_result_v1: TestResultRenderer,
  knowledge_check_v1: KnowledgeCheckPlaceholder,
  model_code_review_v1: ModelCodeReviewPlaceholder,
  sql_workspace_v1: SqlWorkspacePlaceholder,
  demonstration_v1: DemonstrationPlaceholder,
  source_inspector_v1: SourceInspectorPlaceholder,
} satisfies Record<ArtifactPresentationType, ArtifactRenderer>;

export const ARTIFACT_PRESENTATION_TYPES = Object.freeze(Object.keys(ARTIFACT_RENDERER_REGISTRY) as ArtifactPresentationType[]);

export function artifactRendererFor(type: string): ArtifactRenderer | null {
  if (!Object.prototype.hasOwnProperty.call(ARTIFACT_RENDERER_REGISTRY, type)) return null;
  return ARTIFACT_RENDERER_REGISTRY[type as ArtifactPresentationType];
}

function ExerciseWorkspacePlaceholder({ artifact }: ArtifactRendererProps) {
  const presentation = artifact.presentation;
  if (presentation.type !== "exercise_workspace_v1") return <ArtifactContractError />;
  return <ArtifactPlaceholder label="代码练习"><span>{presentation.language_id} · {presentation.editor_mode}</span></ArtifactPlaceholder>;
}

function BrowserPreviewPlaceholder({ artifact }: ArtifactRendererProps) {
  if (artifact.presentation.type !== "browser_preview_v1") return <ArtifactContractError />;
  return <ArtifactPlaceholder label="浏览器预览"><span>隔离预览</span></ArtifactPlaceholder>;
}

function TestResultRenderer({ artifact, loadAttempt, onReturnToSource }: ArtifactRendererProps) {
  if (artifact.presentation.type !== "test_result_v1") return <ArtifactContractError />;
  return <ExecutionResultArtifact artifact={artifact} loadAttempt={loadAttempt} onReturnToSource={onReturnToSource} />;
}

function KnowledgeCheckPlaceholder({ artifact }: ArtifactRendererProps) {
  const presentation = artifact.presentation;
  if (presentation.type !== "knowledge_check_v1") return <ArtifactContractError />;
  return <ArtifactPlaceholder label="结构化检查"><SafeMarkdown markdown={presentation.prompt_markdown} surface="artifact" /></ArtifactPlaceholder>;
}

function ModelCodeReviewPlaceholder({ artifact }: ArtifactRendererProps) {
  if (artifact.presentation.type !== "model_code_review_v1") return <ArtifactContractError />;
  const presentation = artifact.presentation;
  return <ArtifactPlaceholder label="代码审查"><span>{presentation.language_id} · {presentation.line_count} 行</span></ArtifactPlaceholder>;
}

function SqlWorkspacePlaceholder({ artifact }: ArtifactRendererProps) {
  const presentation = artifact.presentation;
  if (presentation.type !== "sql_workspace_v1") return <ArtifactContractError />;
  return <ArtifactPlaceholder label="SQL 工作区"><span>{presentation.dialect} · 最多 {presentation.max_rows} 行</span></ArtifactPlaceholder>;
}

function DemonstrationPlaceholder({ artifact }: ArtifactRendererProps) {
  const presentation = artifact.presentation;
  if (presentation.type !== "demonstration_v1") return <ArtifactContractError />;
  return <ArtifactPlaceholder label="教学演示"><span>{presentation.demonstration_mode === "interactive" ? "交互演示" : "静态演示"}</span></ArtifactPlaceholder>;
}

function SourceInspectorPlaceholder({ artifact }: ArtifactRendererProps) {
  const presentation = artifact.presentation;
  if (presentation.type !== "source_inspector_v1") return <ArtifactContractError />;
  return <ArtifactPlaceholder label="来源定位"><p>{presentation.excerpt}</p></ArtifactPlaceholder>;
}

function ArtifactPlaceholder({ label, children }: { label: string; children: ReactNode }) {
  return <section className="inline-artifact-placeholder" aria-label={label}>{children}</section>;
}

function ArtifactContractError() {
  return <div className="inline-artifact-contract-error" role="alert">ARTIFACT_PRESENTATION_CONTRACT_ERROR</div>;
}
