import { useSyncExternalStore } from "react";

import type { TutorPublicArtifactItem } from "../../../types";

export type SqlArtifactDraftState = {
  query: string;
  starterQueryHash: string;
  artifactVersion: number;
  learningTrackId: string;
  knowledgeKey: string;
  teachingSessionId: string;
  lastRunQuery: string | null;
  viewState: unknown;
};

const drafts = new Map<string, SqlArtifactDraftState>();
const listeners = new Map<string, Set<() => void>>();

export function useSqlArtifactDraft(artifact: TutorPublicArtifactItem): SqlArtifactDraftState {
  const presentation = artifact.presentation;
  if (presentation.type !== "sql_workspace_v2") {
    throw new Error("SQL Artifact draft requires sql_workspace_v2");
  }
  const key = identity(artifact.conversation_id, artifact.id);
  ensureDraft(key, artifact, presentation);
  return useSyncExternalStore(
    (listener) => subscribe(key, listener),
    () => drafts.get(key)!,
    () => drafts.get(key)!,
  );
}

export function updateSqlArtifactQuery(conversationId: string, artifactId: string, query: string): void {
  const key = identity(conversationId, artifactId);
  const current = drafts.get(key);
  if (!current || current.query === query) return;
  drafts.set(key, { ...current, query });
  emit(key);
}

export function markSqlArtifactRun(conversationId: string, artifactId: string, query: string): void {
  const key = identity(conversationId, artifactId);
  const current = drafts.get(key);
  if (!current) return;
  drafts.set(key, { ...current, lastRunQuery: query });
  emit(key);
}

export function saveSqlArtifactViewState(conversationId: string, artifactId: string, viewState: unknown): void {
  const current = drafts.get(identity(conversationId, artifactId));
  if (!current) return;
  drafts.set(identity(conversationId, artifactId), { ...current, viewState });
}

export function resetSqlArtifactDraftsForTests(): void {
  drafts.clear();
  listeners.clear();
}

function ensureDraft(
  key: string,
  artifact: TutorPublicArtifactItem,
  presentation: Extract<TutorPublicArtifactItem["presentation"], { type: "sql_workspace_v2" }>,
): void {
  const current = drafts.get(key);
  const sameScope = current && current.learningTrackId === artifact.learning_track_id &&
    current.knowledgeKey === artifact.knowledge_key && current.teachingSessionId === artifact.teaching_session_id;
  if (current && sameScope) {
    if (artifact.version > current.artifactVersion) {
      drafts.set(key, { ...current, starterQueryHash: presentation.starter_query_hash, artifactVersion: artifact.version });
    }
    return;
  }
  drafts.set(key, {
    query: presentation.starter_query,
    starterQueryHash: presentation.starter_query_hash,
    artifactVersion: artifact.version,
    learningTrackId: artifact.learning_track_id,
    knowledgeKey: artifact.knowledge_key,
    teachingSessionId: artifact.teaching_session_id,
    lastRunQuery: null,
    viewState: null,
  });
}

function identity(conversationId: string, artifactId: string): string {
  return JSON.stringify([conversationId, artifactId]);
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
