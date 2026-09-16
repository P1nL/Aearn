import type { TutorArtifactAttemptDetail, TutorPublicArtifactItem, TutorPublicBranchGroup } from "../../../types";
import type { TutorArtifactAttemptLoader } from "./artifactRendererTypes";

export type ArtifactRendererUiState = {
  expanded: boolean;
  component: Readonly<Record<string, unknown>>;
  model: unknown;
  scrollTop: number;
  tab: string | null;
  terminalCollapseMarker: string | null;
};

type BranchUiState = {
  expanded: boolean;
  serverState: TutorPublicBranchGroup["state"];
};

const artifactUiStateCache = new Map<string, ArtifactRendererUiState>();
const latestArtifactKeyByIdentity = new Map<string, string>();
const artifactDetailCache = new Map<string, Promise<TutorPublicArtifactItem>>();
const artifactAttemptCache = new Map<string, Promise<TutorArtifactAttemptDetail>>();
const branchUiStateCache = new Map<string, BranchUiState>();

export function artifactUiStateKey(artifact: TutorPublicArtifactItem): string {
  return `${artifact.conversation_id}:${artifact.id}:${artifact.version}`;
}

export function readArtifactUiState(
  artifact: TutorPublicArtifactItem,
  defaultExpanded: boolean,
): ArtifactRendererUiState {
  const key = artifactUiStateKey(artifact);
  const existing = artifactUiStateCache.get(key);
  if (existing) return existing;
  const identity = artifactIdentity(artifact);
  const priorKey = latestArtifactKeyByIdentity.get(identity);
  const prior = priorKey ? artifactUiStateCache.get(priorKey) : null;
  const next: ArtifactRendererUiState = prior
    ? { ...prior, component: { ...prior.component } }
    : {
        expanded: defaultExpanded,
        component: {},
        model: null,
        scrollTop: 0,
        tab: null,
        terminalCollapseMarker: null,
      };
  artifactUiStateCache.set(key, next);
  latestArtifactKeyByIdentity.set(identity, key);
  return next;
}

export function writeArtifactUiState(
  artifact: TutorPublicArtifactItem,
  update: Partial<ArtifactRendererUiState>,
): ArtifactRendererUiState {
  const key = artifactUiStateKey(artifact);
  const current = readArtifactUiState(artifact, !isTerminalArtifact(artifact));
  const next = { ...current, ...update };
  artifactUiStateCache.set(key, next);
  latestArtifactKeyByIdentity.set(artifactIdentity(artifact), key);
  return next;
}

export function loadArtifactDetailCached(
  artifact: TutorPublicArtifactItem,
  loader: (artifact: TutorPublicArtifactItem) => Promise<TutorPublicArtifactItem>,
): Promise<TutorPublicArtifactItem> {
  const key = artifactUiStateKey(artifact);
  const existing = artifactDetailCache.get(key);
  if (existing) return existing;
  const pending = loader(artifact).then((detail) => {
    if (!sameArtifactProjection(artifact, detail)) {
      throw new Error("Tutor Artifact detail identity changed during lazy load");
    }
    return detail;
  }).catch((error: unknown) => {
    if (artifactDetailCache.get(key) === pending) artifactDetailCache.delete(key);
    throw error;
  });
  artifactDetailCache.set(key, pending);
  return pending;
}

export function loadArtifactAttemptCached(
  artifact: TutorPublicArtifactItem,
  attemptId: string,
  loader: TutorArtifactAttemptLoader,
): Promise<TutorArtifactAttemptDetail> {
  const key = `${artifactUiStateKey(artifact)}:attempt:${attemptId}`;
  const existing = artifactAttemptCache.get(key);
  if (existing) return existing;
  const pending = loader({ artifact, attemptId }).then((detail) => {
    if (!sameAttemptScope(artifact, attemptId, detail)) {
      throw new Error("Tutor Artifact Attempt detail identity changed during lazy load");
    }
    return detail;
  }).catch((error: unknown) => {
    if (artifactAttemptCache.get(key) === pending) artifactAttemptCache.delete(key);
    throw error;
  });
  artifactAttemptCache.set(key, pending);
  return pending;
}

export function readBranchExpanded(conversationId: string, branch: TutorPublicBranchGroup): boolean {
  if (branch.state === "active") {
    branchUiStateCache.set(branchStateKey(conversationId, branch.branch_id), { expanded: true, serverState: "active" });
    return true;
  }
  const key = branchStateKey(conversationId, branch.branch_id);
  const current = branchUiStateCache.get(key);
  if (!current || current.serverState !== branch.state) {
    branchUiStateCache.set(key, { expanded: false, serverState: branch.state });
    return false;
  }
  return current.expanded;
}

export function writeBranchExpanded(conversationId: string, branch: TutorPublicBranchGroup, expanded: boolean): void {
  if (branch.state === "active") return;
  branchUiStateCache.set(branchStateKey(conversationId, branch.branch_id), { expanded, serverState: branch.state });
}

export function isTerminalArtifact(artifact: TutorPublicArtifactItem): boolean {
  return artifact.state === "completed"
    || artifact.state === "failed"
    || artifact.state === "cancelled"
    || artifact.state === "superseded";
}

export function resetArtifactUiStateCachesForTests(): void {
  artifactUiStateCache.clear();
  latestArtifactKeyByIdentity.clear();
  artifactDetailCache.clear();
  artifactAttemptCache.clear();
  branchUiStateCache.clear();
}

function artifactIdentity(artifact: TutorPublicArtifactItem): string {
  return `${artifact.conversation_id}:${artifact.id}`;
}

function branchStateKey(conversationId: string, branchId: string): string {
  return `${conversationId}:${branchId}`;
}

function sameArtifactProjection(left: TutorPublicArtifactItem, right: TutorPublicArtifactItem): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function sameAttemptScope(
  artifact: TutorPublicArtifactItem,
  attemptId: string,
  detail: TutorArtifactAttemptDetail,
): boolean {
  return detail.artifact_id === artifact.id &&
    detail.artifact_version === artifact.version &&
    detail.conversation_id === artifact.conversation_id &&
    detail.learning_track_id === artifact.learning_track_id &&
    detail.knowledge_key === artifact.knowledge_key &&
    detail.teaching_session_id === artifact.teaching_session_id &&
    detail.attempt_id === attemptId;
}
