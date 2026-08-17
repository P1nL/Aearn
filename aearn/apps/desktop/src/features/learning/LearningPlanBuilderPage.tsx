import { useCallback, useEffect, useState } from "react";

import {
  cancelLearningPlanSession,
  confirmLearningPlanSession,
  fetchLearningPlanSession,
} from "../../api";
import { getErrorInfo } from "../../lib/errorMessages";
import type { LearningPlanDraft, LearningPlanSession, UserProfile } from "../../types";
import { TutorConversationSurface } from "../tutor/TutorConversationSurface";

type LearningPlanBuilderPageProps = {
  user: UserProfile;
  initialSession: LearningPlanSession;
  onBack: () => void;
  onConfirmed: (trackId: string) => void;
};

export function LearningPlanBuilderPage({ user, initialSession, onBack, onConfirmed }: LearningPlanBuilderPageProps) {
  const [session, setSession] = useState(initialSession);
  const [status, setStatus] = useState<"idle" | "loading" | "confirming" | "cancelling">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [draftOpen, setDraftOpen] = useState(true);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setStatus((current) => current === "idle" ? "loading" : current);
    try {
      const next = await fetchLearningPlanSession(user.id, initialSession.session_id, signal);
      if (signal?.aborted) return;
      setSession(next);
      setErrorMessage(null);
    } catch (error) {
      if (!signal?.aborted) setErrorMessage(getErrorInfo(error).message);
    } finally {
      setStatus((current) => current === "loading" ? "idle" : current);
    }
  }, [initialSession.session_id, user.id]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  async function cancel() {
    setStatus("cancelling");
    setErrorMessage(null);
    try {
      await cancelLearningPlanSession({
        userId: user.id,
        sessionId: session.session_id,
        expectedSessionVersion: session.version,
        clientActionId: createLearningActionId("learning-plan-cancel"),
      });
      onBack();
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setStatus("idle");
    }
  }

  async function confirm() {
    if (!session.current_draft) return;
    setStatus("confirming");
    setErrorMessage(null);
    try {
      const result = await confirmLearningPlanSession({
        userId: user.id,
        session,
        clientActionId: createLearningActionId("learning-plan-confirm"),
      });
      setSession(result.session);
      onConfirmed(result.track.track_id);
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
      await refresh();
    } finally {
      setStatus("idle");
    }
  }

  const draft = session.current_draft;
  const draftId = draft?.draft_id ?? null;

  useEffect(() => {
    if (draftId) setDraftOpen(true);
  }, [draftId]);

  const sessionStatus = status === "loading"
    ? "正在同步"
    : draft
      ? `计划草案 v${draft.draft_version}`
      : "正在收集计划信息";

  return (
    <main className={`learning-plan-builder${draft ? " draft-visible" : " collecting"}`} aria-labelledby="learning-plan-builder-title">
      <header className="learning-plan-builder-toolbar">
        <button className="learning-plan-back" type="button" onClick={onBack} aria-label="返回学习主线首页">
          <span aria-hidden="true">←</span>
          <span>返回</span>
        </button>
        <div className="learning-plan-builder-context">
          <span>Aearn Tutor</span>
          <strong id="learning-plan-builder-title">制定学习计划</strong>
        </div>
        <div className="learning-plan-builder-actions">
          <span className={`learning-plan-session-state${draft ? " ready" : ""}`} role="status" aria-live="polite">
            {sessionStatus}
          </span>
          <button className="tutor-text-button" type="button" onClick={() => void cancel()} disabled={status !== "idle"}>
            {status === "cancelling" ? "正在取消……" : "取消计划"}
          </button>
        </div>
      </header>

      {session.last_error && (
        <div className="tutor-inline-error learning-plan-builder-error" role="alert">
          <strong>{session.last_error.code}</strong>
          <span>草案未通过安全或质量门。会话已保留，请调整要求后重试。</span>
        </div>
      )}
      {errorMessage && (
        <div className="tutor-inline-error learning-plan-builder-error" role="alert">
          <span>{errorMessage}</span>
          <button className="tutor-text-button" type="button" onClick={() => void refresh()}>刷新</button>
        </div>
      )}

      <section className="learning-plan-builder-flow">
        <div className="learning-plan-conversation-column">
          <TutorConversationSurface
            user={user}
            enabled
            isActive
            selectedConversationId={session.conversation_id}
            onSelectConversation={() => undefined}
            onConversationsChanged={() => window.setTimeout(() => void refresh(), 120)}
            mode="plan_drafting"
            planningComposerPlaceholder={draft ? "对计划有修改意见？直接告诉我……" : undefined}
            showControls={false}
          />
        </div>
      </section>

      <div className={`learning-plan-draft-dock${draftOpen ? " open" : ""}`}>
        <button
          className="learning-plan-draft-toggle"
          type="button"
          aria-expanded={draftOpen}
          aria-controls="learning-plan-draft-panel"
          aria-label={draftOpen ? "收起计划窗口" : "展开计划窗口"}
          title={draftOpen ? "收起计划窗口" : "展开计划窗口"}
          onClick={() => setDraftOpen((current) => !current)}
        >
          <span aria-hidden="true">{draftOpen ? "→" : "←"}</span>
        </button>
        {draftOpen ? (
          draft ? (
            <LearningPlanDraftCard
              draft={draft}
              busy={status === "confirming"}
              onConfirm={() => void confirm()}
            />
          ) : (
            <LearningPlanDraftEmpty />
          )
        ) : null}
      </div>
    </main>
  );
}

function LearningPlanDraftEmpty() {
  return (
    <aside
      id="learning-plan-draft-panel"
      className="learning-plan-draft-card learning-plan-draft-empty"
      aria-label="计划尚未生成"
      role="status"
    >
      <span className="learning-plan-draft-empty-emoji" aria-hidden="true">🧭</span>
      <span className="visually-hidden">计划尚未生成</span>
    </aside>
  );
}

function LearningPlanDraftCard({ draft, busy, onConfirm }: { draft: LearningPlanDraft; busy: boolean; onConfirm: () => void }) {
  return (
    <aside id="learning-plan-draft-panel" className="learning-plan-draft-card" aria-labelledby="learning-plan-draft-title">
      <header className="learning-plan-draft-heading">
        <div>
          <p className="tutor-panel-eyebrow">计划路线 · 草案 v{draft.draft_version}</p>
          <h2 id="learning-plan-draft-title">{draft.plan.title}</h2>
        </div>
        <span>{draft.profile.weekly_minutes} 分钟 / 周</span>
      </header>
      <p className="learning-plan-draft-goal">{draft.profile.goal_text}</p>
      <dl className="learning-plan-draft-profile">
        <div><dt>目标阶段</dt><dd>{draft.profile.target_level}</dd></div>
        <div><dt>当前基础</dt><dd>{experienceLabel(draft.profile.experience_level)}</dd></div>
        <div><dt>学习节奏</dt><dd>{draft.profile.pace_summary}</dd></div>
      </dl>
      <div className="learning-plan-route" aria-label="计划路线模块">
        {draft.plan.modules.map((module, index) => (
          <section key={module.module_key}>
            <span className="learning-plan-route-marker" aria-hidden="true">{index + 1}</span>
            <div className="learning-plan-route-content">
              <header>
                <strong>{module.title}</strong>
                {module.is_skippable ? <small>可跳过</small> : null}
              </header>
              <ul>
                {module.nodes.map((node) => (
                  <li key={node.knowledge_key}>
                    <span>{node.title}</span>
                    <small>{node.is_core ? "核心" : "扩展"}</small>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        ))}
      </div>
      <section className="learning-plan-sources">
        <strong>权威来源</strong>
        <div>{draft.sources.map((source) => <span key={source.source_id}>{source.display_name} · {source.trust_tier}</span>)}</div>
      </section>
      <footer>
        <p>你仍可在对话中要求调整。确认后才会创建正式学习主线。</p>
        <button className="tutor-primary-button" type="button" disabled={busy} onClick={onConfirm}>
          {busy ? "正在确认……" : "确认并创建学习主线"}
        </button>
      </footer>
    </aside>
  );
}

function experienceLabel(value: LearningPlanDraft["profile"]["experience_level"]): string {
  return { new: "完全新手", beginner: "初学者", intermediate: "有一定基础", advanced: "进阶学习者" }[value];
}

function createLearningActionId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}:${random}`;
}
