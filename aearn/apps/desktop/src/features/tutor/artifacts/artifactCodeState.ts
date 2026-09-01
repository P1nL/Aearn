import { useSyncExternalStore } from "react";

import type { TutorPublicArtifactItem } from "../../../types";

export type CodeArtifactDraftState = {
  source: string;
  sourceContentHash: string;
  artifactVersion: number;
  languageId: string;
  learningTrackId: string;
  knowledgeKey: string;
  teachingSessionId: string;
  lastRunSource: string | null;
  viewState: unknown;
};

const drafts = new Map<string, CodeArtifactDraftState>();
const listeners = new Map<string, Set<() => void>>();

export function codeArtifactIdentity(conversationId: string, artifactId: string): string {
  return JSON.stringify([conversationId, artifactId]);
}

export function useCodeArtifactDraft(artifact: TutorPublicArtifactItem): CodeArtifactDraftState {
  const presentation = artifact.presentation;
  if (presentation.type !== "exercise_workspace_v1") {
    throw new Error("Code Artifact draft requires exercise_workspace_v1");
  }
  const key = codeArtifactIdentity(artifact.conversation_id, artifact.id);
  ensureDraft(key, artifact, presentation);
  return useSyncExternalStore(
    (listener) => subscribe(key, listener),
    () => drafts.get(key)!,
    () => drafts.get(key)!,
  );
}

export function useCodeArtifactDraftById(
  conversationId: string,
  artifactId: string,
): CodeArtifactDraftState | null {
  const key = codeArtifactIdentity(conversationId, artifactId);
  return useSyncExternalStore(
    (listener) => subscribe(key, listener),
    () => drafts.get(key) ?? null,
    () => drafts.get(key) ?? null,
  );
}

export function updateCodeArtifactSource(
  conversationId: string,
  artifactId: string,
  source: string,
): void {
  const key = codeArtifactIdentity(conversationId, artifactId);
  const current = drafts.get(key);
  if (!current || current.source === source) return;
  drafts.set(key, { ...current, source });
  emit(key);
}

export function markCodeArtifactRun(
  conversationId: string,
  artifactId: string,
  source: string,
): void {
  const key = codeArtifactIdentity(conversationId, artifactId);
  const current = drafts.get(key);
  if (!current) return;
  drafts.set(key, { ...current, lastRunSource: source });
  emit(key);
}

export function saveCodeArtifactViewState(
  conversationId: string,
  artifactId: string,
  viewState: unknown,
): void {
  const key = codeArtifactIdentity(conversationId, artifactId);
  const current = drafts.get(key);
  if (!current) return;
  drafts.set(key, { ...current, viewState });
}

export function resetCodeArtifactDraftsForTests(): void {
  drafts.clear();
  listeners.clear();
}

function ensureDraft(
  key: string,
  artifact: TutorPublicArtifactItem,
  presentation: Extract<TutorPublicArtifactItem["presentation"], { type: "exercise_workspace_v1" }>,
): void {
  const current = drafts.get(key);
  const sameScope = current
    && current.learningTrackId === artifact.learning_track_id
    && current.knowledgeKey === artifact.knowledge_key
    && current.teachingSessionId === artifact.teaching_session_id;
  if (current && sameScope) {
    if (artifact.version > current.artifactVersion) {
      drafts.set(key, {
        ...current,
        sourceContentHash: presentation.starter_content_hash,
        artifactVersion: artifact.version,
        languageId: presentation.language_id,
      });
    }
    return;
  }
  drafts.set(key, {
    source: presentation.starter_content,
    sourceContentHash: presentation.starter_content_hash,
    artifactVersion: artifact.version,
    languageId: presentation.language_id,
    learningTrackId: artifact.learning_track_id,
    knowledgeKey: artifact.knowledge_key,
    teachingSessionId: artifact.teaching_session_id,
    lastRunSource: null,
    viewState: null,
  });
}

function subscribe(key: string, listener: () => void): () => void {
  const target = listeners.get(key) ?? new Set<() => void>();
  target.add(listener);
  listeners.set(key, target);
  return () => {
    target.delete(listener);
    if (target.size === 0) listeners.delete(key);
  };
}

function emit(key: string): void {
  listeners.get(key)?.forEach((listener) => listener());
}
