import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import {
  createOrResumeTutorConversation,
  fetchLearningRoadmap,
  fetchLearningTrackDetail,
  fetchReviewQueue,
} from "../../api";
import { getErrorInfo } from "../../lib/errorMessages";
import type {
  LearningRoadmap,
  LearningScopeInput,
  LearningTrackDetail,
  ReviewQueue,
  TutorContextReference,
  TutorContextReferenceDraft,
  UserProfile,
} from "../../types";
import { TutorConversationSurface, type TutorComposerReference } from "../tutor/TutorConversationSurface";
import { LearningRoadmapPanel } from "./LearningRoadmapPanel";
import { LessonDocumentPage } from "./LessonDocumentPage";
import { ReviewSessionPanel } from "./ReviewSessionPanel";

export type LearningWorkspaceMode = "lesson" | "review";

export type LearningWorkspaceNavigation = {
  trackId: string;
  mode: LearningWorkspaceMode;
  knowledgeKey: string | null;
  reviewSessionId: string | null;
};

type TrackLearningWorkspaceProps = {
  user: UserProfile;
  trackId: string;
  initialMode?: LearningWorkspaceMode;
  initialKnowledgeKey?: string | null;
  initialReviewSessionId?: string | null;
  onBack: () => void;
};

type WorkspacePanel = "roadmap" | "learning" | "tutor";
type WorkspaceStatus = "loading" | "ready" | "error";

const STORAGE_VERSION = 1;

export function TrackLearningWorkspace({
  user,
  trackId,
  initialMode = "lesson",
  initialKnowledgeKey,
  initialReviewSessionId,
  onBack,
}: TrackLearningWorkspaceProps) {
  const [status, setStatus] = useState<WorkspaceStatus>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [track, setTrack] = useState<LearningTrackDetail | null>(null);
  const [roadmap, setRoadmap] = useState<LearningRoadmap | null>(null);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueue | null>(null);
  const [mode, setMode] = useState<LearningWorkspaceMode>(initialMode);
  const [knowledgeKey, setKnowledgeKey] = useState<string | null>(initialKnowledgeKey ?? null);
  const [reviewSessionId, setReviewSessionId] = useState<string | null>(initialReviewSessionId ?? null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [references, setReferences] = useState<TutorComposerReference[]>([]);
  const [referenceTaskKind, setReferenceTaskKind] = useState<NonNullable<LearningScopeInput["task_kind"]> | null>(null);
  const [activePanel, setActivePanel] = useState<WorkspacePanel>("learning");
  const [roadmapDrawerOpen, setRoadmapDrawerOpen] = useState(false);
  const roadmapDrawerRef = useRef<HTMLElement | null>(null);
  const roadmapDrawerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const roadmapDrawerCloseRef = useRef<HTMLButtonElement | null>(null);

  const loadAuthority = useCallback(async (signal?: AbortSignal) => {
    setStatus("loading");
    setErrorMessage(null);
    try {
      const [nextTrack, nextRoadmap, nextQueue, conversation] = await Promise.all([
        fetchLearningTrackDetail(user.id, trackId, signal),
        fetchLearningRoadmap(user.id, trackId, signal),
        fetchReviewQueue(user.id, trackId, signal),
        createOrResumeTutorConversation({
          userId: user.id,
          clientActionId: workspaceConversationActionId(user.id, trackId),
          learningScope: { scope_kind: "learning_track", learning_track_id: trackId },
        }),
      ]);
      if (signal?.aborted) return;
      const availableKeys = new Set(nextRoadmap.modules.flatMap((module) => module.nodes.filter((node) => node.progress_status !== "locked").map((node) => node.knowledge_key)));
      setTrack(nextTrack);
      setRoadmap(nextRoadmap);
      setReviewQueue(nextQueue);
      setConversationId(conversation.conversation_id);
      setKnowledgeKey((current) => {
        const requestedKey = current ?? initialKnowledgeKey ?? nextTrack.current_knowledge_key;
        return requestedKey && availableKeys.has(requestedKey)
          ? requestedKey
          : nextTrack.current_knowledge_key && availableKeys.has(nextTrack.current_knowledge_key)
            ? nextTrack.current_knowledge_key
            : [...availableKeys][0] ?? null;
      });
      setMode((current) => current === "review" && nextQueue.items.length === 0 && !initialReviewSessionId ? "lesson" : current);
      setStatus("ready");
    } catch (error) {
      if (signal?.aborted) return;
      const info = getErrorInfo(error);
      setErrorMessage(info.message);
      setStatus("error");
      if (info.code === "LEARNING_TRACK_NOT_FOUND" || info.code === "NOT_FOUND") clearLearningWorkspaceNavigation(user.id);
    }
  }, [initialKnowledgeKey, initialReviewSessionId, trackId, user.id]);

  useEffect(() => {
    const controller = new AbortController();
    void loadAuthority(controller.signal);
    return () => controller.abort();
  }, [loadAuthority]);

  useEffect(() => {
    if (status !== "ready") return;
    writeLearningWorkspaceNavigation(user.id, { trackId, mode, knowledgeKey, reviewSessionId });
  }, [knowledgeKey, mode, reviewSessionId, status, trackId, user.id]);

  useEffect(() => {
    setReferences([]);
    setReferenceTaskKind(null);
  }, [mode, knowledgeKey, reviewSessionId, trackId, user.id]);

  useEffect(() => {
    if (!roadmapDrawerOpen) return;
    const frame = globalThis.requestAnimationFrame(() => roadmapDrawerCloseRef.current?.focus());
    return () => globalThis.cancelAnimationFrame(frame);
  }, [roadmapDrawerOpen]);

  const tutorScope = useMemo<LearningScopeInput>(() => {
    const scopedKey = references[0]?.draft.knowledge_key ?? knowledgeKey ?? undefined;
    const taskKind = referenceTaskKind ?? (mode === "review" ? "review_coaching" : "lesson_teaching");
    return {
      scope_kind: "learning_track",
      learning_track_id: trackId,
      task_kind: taskKind,
      ...(scopedKey ? { knowledge_key: scopedKey } : {}),
    };
  }, [knowledgeKey, mode, referenceTaskKind, references, trackId]);

  function addReference(draft: TutorContextReferenceDraft, label: string, taskKind: NonNullable<LearningScopeInput["task_kind"]>) {
    const identity = referenceIdentity(draft);
    setReferences((current) => {
      const sameScope = current.length === 0 || (current[0].draft.knowledge_key === draft.knowledge_key && referenceTaskKind === taskKind);
      const base = sameScope ? current : [];
      if (base.some((item) => referenceIdentity(item.draft) === identity)) return base;
      if (base.length >= 6) return base;
      return [...base, { id: identity, draft, label }];
    });
    setReferenceTaskKind(taskKind);
    setActivePanel("tutor");
  }

  function openLesson(nextKnowledgeKey: string) {
    setMode("lesson");
    setKnowledgeKey(nextKnowledgeKey);
    setReviewSessionId(null);
    setRoadmapDrawerOpen(false);
    setActivePanel("learning");
  }

  function openReview(nextKnowledgeKey?: string) {
    setMode("review");
    setKnowledgeKey(nextKnowledgeKey ?? reviewQueue?.critical_prerequisite_gate?.knowledge_key ?? reviewQueue?.items[0]?.knowledge_key ?? knowledgeKey);
    setRoadmapDrawerOpen(false);
    setActivePanel("learning");
  }

  async function refreshAuthority() {
    const controller = new AbortController();
    await loadAuthority(controller.signal);
  }

  function closeRoadmapDrawer() {
    setRoadmapDrawerOpen(false);
    globalThis.requestAnimationFrame(() => roadmapDrawerTriggerRef.current?.focus());
  }

  function handleRoadmapDrawerKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeRoadmapDrawer();
      return;
    }
    if (event.key !== "Tab" || !roadmapDrawerRef.current) return;
    const focusable = [...roadmapDrawerRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  if (status === "loading" && !track) {
    return <section className="learning-workspace-status" aria-live="polite"><span aria-hidden="true" /><div><p className="tutor-panel-eyebrow">Learning workspace</p><h1>正在恢复学习工作区</h1><p>正在并行读取 track、roadmap、Review queue 与 track-scoped Tutor conversation。</p></div></section>;
  }

  if (status === "error" || !track || !roadmap || !reviewQueue || !conversationId) {
    return <section className="learning-workspace-status error" role="alert"><span aria-hidden="true">!</span><div><p className="tutor-panel-eyebrow">恢复未完成</p><h1>无法读取当前工作区</h1><p>{errorMessage ?? "服务器返回了不完整的学习状态。"}</p><div><button className="tutor-primary-button" type="button" onClick={() => void loadAuthority()}>重试</button><button className="tutor-text-button" type="button" onClick={onBack}>返回学习主线</button></div></div></section>;
  }

  const scopeTitle = `${track.language_display_name} · ${knowledgeTitle(roadmap, tutorScope.knowledge_key ?? null)} · ${taskLabel(tutorScope.task_kind)}`;

  return (
    <main className="track-learning-workspace" aria-label={`${track.language_display_name} 学习工作区`}>
      <header className="learning-workspace-toolbar">
        <button className="tutor-text-button" type="button" onClick={onBack}>← 学习主线</button>
        <div><span>{track.language_display_name} · {track.target_level}</span><strong>{track.active_plan_title}</strong></div>
        <div className="learning-workspace-toolbar-actions">
          <button ref={roadmapDrawerTriggerRef} className="tutor-compact-button quiet learning-roadmap-drawer-trigger" type="button" aria-expanded={roadmapDrawerOpen} aria-controls="learning-roadmap-drawer" onClick={() => setRoadmapDrawerOpen((current) => !current)}>学习路线</button>
          <span>{track.progress.percent}%</span>
        </div>
      </header>

      <nav className="learning-workspace-tabs" aria-label="工作区面板">
        {(["roadmap", "learning", "tutor"] as const).map((panel) => <button key={panel} className={activePanel === panel ? "active" : ""} type="button" aria-pressed={activePanel === panel} onClick={() => setActivePanel(panel)}>{panelLabel(panel, mode, references.length)}</button>)}
      </nav>

      <div className="learning-workspace-grid">
        <aside className={`learning-workspace-roadmap ${activePanel === "roadmap" ? "mobile-active" : ""}`} aria-label="路线面板">
          <LearningRoadmapPanel roadmap={roadmap} reviewQueue={reviewQueue} selectedKnowledgeKey={knowledgeKey} mode={mode} onSelectLesson={openLesson} onOpenReview={openReview} />
        </aside>

        <section className={`learning-workspace-center ${activePanel === "learning" ? "mobile-active" : ""}`} aria-label={mode === "review" ? "复习面板" : "课程面板"}>
          {mode === "lesson" && knowledgeKey ? (
            <LessonDocumentPage userId={user.id} trackId={trackId} knowledgeKey={knowledgeKey} embedded onContextReference={addReference} />
          ) : (
            <ReviewSessionPanel userId={user.id} track={track} queue={reviewQueue} initialKnowledgeKey={knowledgeKey} initialSessionId={reviewSessionId} onSessionChange={setReviewSessionId} onQueueRefresh={refreshAuthority} onContextReference={(draft, label) => addReference(draft, label, "review_coaching")} />
          )}
        </section>

        <aside className={`learning-workspace-tutor ${activePanel === "tutor" ? "mobile-active" : ""}`} aria-label="Tutor 面板">
          <TutorConversationSurface
            user={user}
            enabled
            isActive
            selectedConversationId={conversationId}
            onSelectConversation={setConversationId}
            mode="general"
            showControls={false}
            learningScope={tutorScope}
            scopeLabel={scopeTitle}
            contextReferences={references}
            onRemoveContextReference={(id) => setReferences((current) => {
              const next = current.filter((item) => item.id !== id);
              if (next.length === 0) setReferenceTaskKind(null);
              return next;
            })}
            onReferencesAccepted={(_saved: TutorContextReference[]) => { setReferences([]); setReferenceTaskKind(null); }}
          />
        </aside>
      </div>

      {roadmapDrawerOpen ? <div className="learning-roadmap-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeRoadmapDrawer(); }}><aside ref={roadmapDrawerRef} id="learning-roadmap-drawer" className="learning-roadmap-drawer" role="dialog" aria-modal="true" aria-label="学习路线抽屉" onKeyDown={handleRoadmapDrawerKeyDown}><header><strong>学习路线</strong><button ref={roadmapDrawerCloseRef} className="tutor-text-button" type="button" onClick={closeRoadmapDrawer}>关闭</button></header><LearningRoadmapPanel roadmap={roadmap} reviewQueue={reviewQueue} selectedKnowledgeKey={knowledgeKey} mode={mode} onSelectLesson={openLesson} onOpenReview={openReview} /></aside></div> : null}
    </main>
  );
}

export function readLearningWorkspaceNavigation(userId: string): LearningWorkspaceNavigation | null {
  try {
    const raw = globalThis.localStorage?.getItem(storageKey(userId));
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!isRecord(value) || value.version !== STORAGE_VERSION || !isString(value.trackId) || (value.mode !== "lesson" && value.mode !== "review") || !isNullableString(value.knowledgeKey) || !isNullableString(value.reviewSessionId)) return null;
    return { trackId: value.trackId, mode: value.mode, knowledgeKey: value.knowledgeKey, reviewSessionId: value.reviewSessionId };
  } catch {
    return null;
  }
}

export function clearLearningWorkspaceNavigation(userId: string): void {
  globalThis.localStorage?.removeItem(storageKey(userId));
}

function writeLearningWorkspaceNavigation(userId: string, navigation: LearningWorkspaceNavigation): void {
  globalThis.localStorage?.setItem(storageKey(userId), JSON.stringify({ version: STORAGE_VERSION, ...navigation }));
}
function storageKey(userId: string): string { return `aearn.learning-workspace.v1:${userId}`; }
function workspaceConversationActionId(userId: string, trackId: string): string { return `workspace-conversation:${userId}:${trackId}`; }
function referenceIdentity(reference: TutorContextReferenceDraft): string {
  if (reference.kind === "lesson_selection") return `${reference.kind}:${reference.document_id}:${reference.block_id}:${reference.start_offset}:${reference.end_offset}`;
  if (reference.kind === "review_feedback") return `${reference.kind}:${reference.review_session_id}:${reference.attempt_id}`;
  return `${reference.kind}:${reference.attempt_id}`;
}
function knowledgeTitle(roadmap: LearningRoadmap, knowledgeKey: string | null): string { return roadmap.modules.flatMap((module) => module.nodes).find((node) => node.knowledge_key === knowledgeKey)?.title ?? knowledgeKey ?? "Track 范围"; }
function taskLabel(task: LearningScopeInput["task_kind"]): string { return { general_tutor: "一般辅导", plan_drafting: "计划制定", lesson_teaching: "课程讲解", exercise_feedback: "练习反馈", review_coaching: "复习辅导", model_code_review: "代码审核", remediation: "补救学习" }[task ?? "lesson_teaching"]; }
function panelLabel(panel: WorkspacePanel, mode: LearningWorkspaceMode, referenceCount: number): string { if (panel === "roadmap") return "路线"; if (panel === "learning") return mode === "review" ? "复习" : "课程"; return referenceCount > 0 ? `Tutor · ${referenceCount}` : "Tutor"; }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function isString(value: unknown): value is string { return typeof value === "string"; }
function isNullableString(value: unknown): value is string | null { return value === null || typeof value === "string"; }
