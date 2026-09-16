import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import {
  createOrResumeTutorConversation,
  fetchLearningRoadmap,
  fetchLearningTrackDetail,
  fetchReviewQueue,
} from "../../api";
import { getErrorInfo } from "../../lib/errorMessages";
import type {
  ExerciseAttemptState,
  LearningRoadmap,
  LearningScopeInput,
  LearningTrackDetail,
  LessonDocumentReferenceOpenRequest,
  LessonDocumentState,
  LessonFollowState,
  LessonFollowTarget,
  ReviewQueue,
  TeachingActionDescriptor,
  TeachingSessionProjection,
  TutorContextReference,
  TutorContextReferenceDraft,
  UserProfile,
} from "../../types";
import { TutorConversationSurface, type TutorComposerReference } from "../tutor/TutorConversationSurface";
import { LearningRoadmapPanel } from "./LearningRoadmapPanel";
import { LessonDocumentPage } from "./LessonDocumentPage";
import { LessonDocumentDrawer } from "./lesson/LessonDocumentDrawer";
import { ReviewSessionPanel } from "./ReviewSessionPanel";
import { type TeachingAuthorityInput, useTeachingWorkspaceController } from "./useTeachingWorkspaceController";

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

function SidebarToggleIcon({ side }: { side: "left" | "right" }) {
  return <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true" focusable="false">
    <rect x="2.25" y="2.75" width="13.5" height="12.5" rx="2.8" stroke="currentColor" strokeWidth="1.25" />
    <path d={side === "left" ? "M6 3.25V14.75" : "M12 3.25V14.75"} stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
  </svg>;
}

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
  const [roadmapCollapsed, setRoadmapCollapsed] = useState(false);
  const [secondaryCollapsed, setSecondaryCollapsed] = useState(false);
  const [lessonAuthority, setLessonAuthority] = useState<LessonDocumentState | null>(null);
  const [followState, setFollowState] = useState<LessonFollowState>("following");
  const [followConflict, setFollowConflict] = useState<string | null>(null);
  const [documentReference, setDocumentReference] = useState<LessonDocumentReferenceOpenRequest | null>(null);
  const workspaceScopeRef = useRef({ userId: user.id, trackId, knowledgeKey });
  workspaceScopeRef.current = { userId: user.id, trackId, knowledgeKey };
  const routeRefreshRef = useRef<AbortController | null>(null);
  const routeRefreshGenerationRef = useRef(0);
  const roadmapDrawerRef = useRef<HTMLElement | null>(null);
  const roadmapDrawerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const roadmapDrawerCloseRef = useRef<HTMLButtonElement | null>(null);
  const loadAuthorityRef = useRef<(() => Promise<void>) | null>(null);
  const openedAuthorityKeyRef = useRef<string | null>(null);
  const previousSessionIdentityRef = useRef<string | null>(null);
  const documentDrawerTriggerRef = useRef<HTMLElement | null>(null);

  const handleTeachingTransition = useCallback((next: TeachingSessionProjection) => {
    workspaceScopeRef.current.knowledgeKey = next.knowledge_key;
    setKnowledgeKey(next.knowledge_key);
    setMode("lesson");
    setReviewSessionId(null);
    setFollowState("following");
    setFollowConflict(null);
    setActivePanel("learning");
    openedAuthorityKeyRef.current = null;
  }, []);

  const handleNavigationAction = useCallback((descriptor: TeachingActionDescriptor) => {
    if (descriptor.key === "return_roadmap") {
      setRoadmapDrawerOpen(true);
      setActivePanel("roadmap");
      return;
    }
    if (descriptor.key === "view_feedback" || descriptor.key === "start_review") {
      setMode("review");
      setActivePanel("learning");
      return;
    }
    if (descriptor.key === "open_evidence" || descriptor.key === "continue_reading") {
      setActivePanel("learning");
    }
  }, []);

  const teaching = useTeachingWorkspaceController({
    onConflictRefresh: () => loadAuthorityRef.current?.(),
    onTransition: handleTeachingTransition,
    onNavigationAction: handleNavigationAction,
  });

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
  loadAuthorityRef.current = () => loadAuthority();

  const refreshRouteSummary = useCallback(async () => {
    const requestedScope = workspaceScopeRef.current;
    if (requestedScope.userId !== user.id || requestedScope.trackId !== trackId) return;

    routeRefreshRef.current?.abort();
    const controller = new AbortController();
    const generation = routeRefreshGenerationRef.current + 1;
    routeRefreshGenerationRef.current = generation;
    routeRefreshRef.current = controller;
    try {
      const [nextTrack, nextRoadmap, nextQueue] = await Promise.all([
        fetchLearningTrackDetail(user.id, trackId, controller.signal),
        fetchLearningRoadmap(user.id, trackId, controller.signal),
        fetchReviewQueue(user.id, trackId, controller.signal),
      ]);
      const currentScope = workspaceScopeRef.current;
      if (controller.signal.aborted || generation !== routeRefreshGenerationRef.current || currentScope.userId !== user.id || currentScope.trackId !== trackId) return;
      if (nextTrack.track_id !== trackId || nextRoadmap.track_id !== trackId || nextQueue.track_id !== trackId) return;
      setTrack(nextTrack);
      setRoadmap(nextRoadmap);
      setReviewQueue(nextQueue);
    } catch (error) {
      if (controller.signal.aborted || generation !== routeRefreshGenerationRef.current) return;
      setErrorMessage(getErrorInfo(error).message);
      throw error;
    } finally {
      if (routeRefreshRef.current === controller) routeRefreshRef.current = null;
    }
  }, [trackId, user.id]);

  useEffect(() => () => {
    routeRefreshGenerationRef.current += 1;
    routeRefreshRef.current?.abort();
  }, [trackId, user.id]);

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
    setDocumentReference(null);
    documentDrawerTriggerRef.current = null;
  }, [mode, knowledgeKey, reviewSessionId, trackId, user.id]);

  useEffect(() => {
    if (documentReference !== null || !documentDrawerTriggerRef.current) return;
    const trigger = documentDrawerTriggerRef.current;
    documentDrawerTriggerRef.current = null;
    const timer = globalThis.setTimeout(() => trigger.focus({ preventScroll: true }), 0);
    return () => globalThis.clearTimeout(timer);
  }, [documentReference]);

  useEffect(() => {
    if (!roadmapDrawerOpen) return;
    const frame = globalThis.requestAnimationFrame(() => roadmapDrawerCloseRef.current?.focus());
    return () => globalThis.cancelAnimationFrame(frame);
  }, [roadmapDrawerOpen]);

  useEffect(() => {
    const identity = teaching.session ? `${teaching.session.knowledge_key}:${teaching.session.session_id}` : null;
    if (identity && previousSessionIdentityRef.current && identity !== previousSessionIdentityRef.current) {
      setFollowState("following");
      setFollowConflict(null);
    }
    previousSessionIdentityRef.current = identity;
  }, [teaching.session]);

  const handleLessonAuthorityChange = useCallback((next: LessonDocumentState | null) => {
    const scope = workspaceScopeRef.current;
    if (next && (next.track_id !== scope.trackId || next.knowledge_key !== scope.knowledgeKey)) return;
    setLessonAuthority(next);
    if (next?.status !== "ready" || !next.assignment || !conversationId || next.knowledge_key !== scope.knowledgeKey) return;
    const authority: TeachingAuthorityInput = {
      userId: scope.userId,
      trackId: scope.trackId,
      conversationId,
      knowledgeKey: next.knowledge_key,
      trackVersion: next.track_version,
      progressVersion: next.progress_version,
      assignmentVersion: next.assignment.assignment_version,
    };
    const authorityKey = [authority.userId, authority.trackId, authority.conversationId, authority.knowledgeKey, authority.trackVersion, authority.progressVersion, authority.assignmentVersion].join(":");
    const current = teaching.session;
    const currentMatches = current && current.conversation_id === conversationId && current.knowledge_key === next.knowledge_key &&
      current.track_version === next.track_version && current.progress_version === next.progress_version &&
      current.assignment_version === next.assignment.assignment_version && current.document_id === next.assignment.document_id;
    if (currentMatches || openedAuthorityKeyRef.current === authorityKey) return;
    openedAuthorityKeyRef.current = authorityKey;
    // A failed open must stay latched for this exact authority. Clearing here
    // retriggers the child authority effect on every error-state render (409 storm).
    // Explicit refresh remains available; a changed authority gets a new key.
    void teaching.open(authority);
  }, [conversationId, knowledgeKey, teaching, trackId, user.id]);

  const tutorScope = useMemo<LearningScopeInput>(() => {
    const scopedKey = references.find((item) => item.draft.kind !== "teaching_session_message")?.draft.knowledge_key ?? knowledgeKey ?? undefined;
    const taskKind = referenceTaskKind ?? (mode === "review" ? "review_coaching" : "lesson_teaching");
    return {
      scope_kind: "learning_track",
      learning_track_id: trackId,
      task_kind: taskKind,
      ...(scopedKey ? { knowledge_key: scopedKey } : {}),
    };
  }, [knowledgeKey, mode, referenceTaskKind, references, trackId]);

  const followTarget = useMemo(() => teachingFollowTarget(teaching.session, lessonAuthority), [lessonAuthority, teaching.session]);
  const teachingMode = teaching.session?.mode ?? "guided";
  const teachingReady = mode === "lesson" && teaching.session !== null;

  const handleLessonProgressChange = useCallback(async (attempt: ExerciseAttemptState) => {
    const scope = workspaceScopeRef.current;
    if (attempt.track_id !== scope.trackId || attempt.knowledge_key !== scope.knowledgeKey) return;
    if (attempt.status !== "terminal" || (attempt.projected !== true && !attempt.route_changed)) return;
    await refreshRouteSummary();
  }, [refreshRouteSummary]);

  function addReference(
    draft: TutorContextReferenceDraft,
    label: string,
    taskKind: NonNullable<LearningScopeInput["task_kind"]>,
    activateTutor = true,
  ) {
    const identity = referenceIdentity(draft);
    setReferences((current) => {
      const targetsCurrentScope = (reference: TutorContextReferenceDraft) =>
        reference.kind === "teaching_session_message" || reference.knowledge_key === knowledgeKey;
      const sameScope = current.length === 0 || (
        referenceTaskKind === taskKind && targetsCurrentScope(draft) && current.every((item) => targetsCurrentScope(item.draft))
      );
      const base = sameScope ? current : [];
      if (base.some((item) => referenceIdentity(item.draft) === identity)) return base;
      if (base.length >= 6) return base;
      return [...base, { id: identity, draft, label }];
    });
    setReferenceTaskKind(taskKind);
    if (activateTutor) setActivePanel("tutor");
  }

  function openLesson(nextKnowledgeKey: string) {
    setMode("lesson");
    workspaceScopeRef.current.knowledgeKey = nextKnowledgeKey;
    setKnowledgeKey(nextKnowledgeKey);
    setReviewSessionId(null);
    setLessonAuthority(null);
    openedAuthorityKeyRef.current = null;
    setFollowState("following");
    setFollowConflict(null);
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

  function openDocumentReference(request: LessonDocumentReferenceOpenRequest, trigger: HTMLElement) {
    documentDrawerTriggerRef.current = trigger;
    setSecondaryCollapsed(false);
    setDocumentReference(request);
  }

  function closeDocumentReference() {
    setDocumentReference(null);
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
  const workspaceClassName = "learning-workspace-grid content-" + mode + " teaching-" + teachingMode + (roadmapCollapsed ? " roadmap-collapsed" : "") + (secondaryCollapsed ? " secondary-collapsed" : "");
  const roadmapToggleLabel = roadmapCollapsed ? "展开左侧学习路线" : "收起左侧学习路线";
  const secondaryToggleLabel = secondaryCollapsed ? "展开右侧辅助面板" : "收起右侧辅助面板";

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
        {(["roadmap", "learning", "tutor"] as const).map((panel) => <button key={panel} className={activePanel === panel ? "active" : ""} type="button" aria-pressed={activePanel === panel} onClick={() => setActivePanel(panel)}>{panelLabel(panel, mode, teachingMode, references.length)}</button>)}
      </nav>

      <div className={workspaceClassName}>
        <button
          className="learning-workspace-sidebar-toggle left"
          type="button"
          aria-label={roadmapToggleLabel}
          title={roadmapToggleLabel}
          aria-expanded={!roadmapCollapsed}
          aria-controls="learning-workspace-roadmap-panel"
          onClick={() => setRoadmapCollapsed((current) => !current)}
        ><SidebarToggleIcon side="left" /></button>
        <button
          className="learning-workspace-sidebar-toggle right"
          type="button"
          aria-label={secondaryToggleLabel}
          title={secondaryToggleLabel}
          aria-expanded={!secondaryCollapsed}
          aria-controls="learning-workspace-lesson-panel learning-workspace-tutor-panel"
          onClick={() => setSecondaryCollapsed((current) => !current)}
        ><SidebarToggleIcon side="right" /></button>

        <aside id="learning-workspace-roadmap-panel" className={`learning-workspace-roadmap ${activePanel === "roadmap" ? "mobile-active" : ""}`} aria-label="路线面板">
          <LearningRoadmapPanel roadmap={roadmap} reviewQueue={reviewQueue} selectedKnowledgeKey={knowledgeKey} mode={mode} onSelectLesson={openLesson} onOpenReview={openReview} />
        </aside>

        {mode === "lesson" ? <div className="learning-workspace-mode-controls" role="group" aria-label="教学工作区模式">
          {followState === "follow_paused" && followTarget ? <button className="learning-follow-resume" type="button" onClick={() => { setFollowConflict(null); setFollowState("following"); }} title={`回到 ${followTarget.label}`}>回到当前讲解</button> : null}
          <button
            className="learning-workspace-mode-switch"
            type="button"
            aria-label={teachingMode === "guided" ? "切换到自由阅读，课程成为主区域" : "切换到 Guided，Tutor 成为主区域"}
            title={teachingMode === "guided" ? "切换到自由阅读" : "切换到 Guided"}
            aria-busy={teaching.pendingActionKey === "switch-mode" || teaching.pendingActionKey === "escalate-guided"}
            disabled={!teachingReady || teaching.pendingActionKey !== null}
            onClick={() => { if (teachingMode === "guided") setFollowState("follow_paused"); void teaching.switchMode(); }}
          ><span aria-hidden="true">⇄</span></button>
        </div> : null}

        <section id="learning-workspace-lesson-panel" className={`learning-workspace-lesson ${mode === "lesson" && ((teachingMode === "free_reading" && activePanel === "learning") || (teachingMode === "guided" && activePanel === "tutor")) ? "mobile-active" : ""}`} aria-label="课程面板" aria-hidden={mode === "review"}>
          {knowledgeKey ? <LessonDocumentPage
            key={knowledgeKey}
            userId={user.id}
            trackId={trackId}
            knowledgeKey={knowledgeKey}
            embedded
            onContextReference={addReference}
            onAuthorityChange={handleLessonAuthorityChange}
            onProgressChange={handleLessonProgressChange}
            followTarget={followTarget}
            followEnabled={mode === "lesson" && teachingMode === "guided" && followState === "following"}
            onFollowPause={() => { if (mode === "lesson" && teachingMode === "guided") setFollowState("follow_paused"); }}
            onFollowConflict={(message) => { setFollowConflict(message); if (message) setFollowState("follow_paused"); }}
            onOpenDocumentReference={openDocumentReference}
          /> : null}
        </section>

        <section className={`learning-workspace-review ${mode === "review" && activePanel === "learning" ? "mobile-active" : ""}`} aria-label="复习面板" aria-hidden={mode !== "review"}>
          {mode === "review" ? <ReviewSessionPanel userId={user.id} track={track} queue={reviewQueue} initialKnowledgeKey={knowledgeKey} initialSessionId={reviewSessionId} onSessionChange={setReviewSessionId} onQueueRefresh={refreshAuthority} onContextReference={(draft, label) => addReference(draft, label, "review_coaching")} /> : null}
        </section>

        <aside id="learning-workspace-tutor-panel" className={`learning-workspace-tutor ${(mode === "review" && activePanel === "tutor") || (mode === "lesson" && ((teachingMode === "guided" && activePanel === "learning") || (teachingMode === "free_reading" && activePanel === "tutor"))) ? "mobile-active" : ""}`} aria-label="Tutor 面板">
          <TutorConversationSurface
            user={user}
            enabled
            isActive
            selectedConversationId={conversationId}
            onSelectConversation={setConversationId}
            mode="general"
            showControls={false}
            composerVariant="compact"
            learningScope={tutorScope}
            scopeLabel={scopeTitle}
            contextReferences={references}
            activeTeachingSessionId={teaching.session?.session_id ?? null}
            teachingActionShelf={mode === "lesson" ? teaching.session?.action_shelf ?? null : null}
            pendingTeachingActionKey={teaching.pendingActionKey}
            onTeachingAction={(descriptor) => void teaching.performAction(descriptor)}
            onTeachingAuthorityChanged={() => { if (mode === "lesson") void teaching.refresh(); }}
            onRemoveContextReference={(id) => setReferences((current) => {
              const next = current.filter((item) => item.id !== id);
              if (next.length === 0) setReferenceTaskKind(null);
              return next;
            })}
            onReferencesAccepted={(_saved: TutorContextReference[]) => { setReferences([]); setReferenceTaskKind(null); }}
            onHistoricalMessageReference={mode === "lesson" ? (draft, label) => addReference(draft, label, "lesson_teaching", false) : undefined}
            onOpenDocumentReference={openDocumentReference}
          />
        </aside>
      </div>

      {documentReference ? <LessonDocumentDrawer
        userId={user.id}
        trackId={trackId}
        conversationId={conversationId}
        request={documentReference}
        onClose={closeDocumentReference}
      /> : null}

      {(teaching.error || followConflict) ? <div className="learning-workspace-authority-notice" role="alert"><strong>{teaching.error?.code ?? "LESSON_FOLLOW_CONFLICT"}</strong><span>{teaching.error?.message ?? followConflict}</span><button className="tutor-text-button" type="button" onClick={() => { setFollowConflict(null); void teaching.refresh(); }}>刷新 authority</button></div> : null}

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
  if (reference.kind === "teaching_session_message") return `${reference.kind}:${reference.teaching_session_id}:${reference.message_id}`;
  return `${reference.kind}:${reference.attempt_id}`;
}
function teachingFollowTarget(session: TeachingSessionProjection | null, lesson: LessonDocumentState | null): LessonFollowTarget | null {
  if (!session?.checkpoint?.active_focus || session.checkpoint.active_focus.focus_kind !== "lesson_block" || lesson?.status !== "ready" || !lesson.assignment || !lesson.document) return null;
  const handle = session.checkpoint.active_focus.source_handles.find((item) => item.startsWith("lesson_block:"));
  if (!handle) return null;
  const blockId = handle.slice("lesson_block:".length);
  if (!blockId || !lesson.document.blocks.some((block) => block.block_id === blockId)) return null;
  if (session.assignment_id !== lesson.assignment.assignment_id || session.assignment_version !== lesson.assignment.assignment_version || session.document_id !== lesson.assignment.document_id) return null;
  return { block_id: blockId, document_id: session.document_id, document_content_hash: lesson.document.content_hash, label: session.checkpoint.active_focus.summary };
}
function knowledgeTitle(roadmap: LearningRoadmap, knowledgeKey: string | null): string { return roadmap.modules.flatMap((module) => module.nodes).find((node) => node.knowledge_key === knowledgeKey)?.title ?? knowledgeKey ?? "Track 范围"; }
function taskLabel(task: LearningScopeInput["task_kind"]): string { return { general_tutor: "一般辅导", plan_drafting: "计划制定", lesson_teaching: "课程讲解", exercise_feedback: "练习反馈", review_coaching: "复习辅导", model_code_review: "代码审核", remediation: "补救学习" }[task ?? "lesson_teaching"]; }
function panelLabel(panel: WorkspacePanel, mode: LearningWorkspaceMode, teachingMode: "guided" | "free_reading", referenceCount: number): string { if (panel === "roadmap") return "路线"; if (panel === "learning") return mode === "review" ? "复习" : teachingMode === "guided" ? "Tutor 主区" : "课程主区"; return referenceCount > 0 ? `Tutor · ${referenceCount}` : teachingMode === "guided" ? "课程" : "Tutor"; }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function isString(value: unknown): value is string { return typeof value === "string"; }
function isNullableString(value: unknown): value is string | null { return value === null || typeof value === "string"; }
