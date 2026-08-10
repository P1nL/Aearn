import { useCallback, useEffect, useState } from "react";

import {
  createLearningPlanSession,
  fetchCurrentLearningPlanSession,
  fetchLearningTracks,
} from "../../api";
import { getErrorInfo } from "../../lib/errorMessages";
import type {
  LearningPlanSession,
  LearningTrackSummary,
  UserProfile,
} from "../../types";

type LearningHomePageProps = {
  user: UserProfile;
  refreshKey: number;
  highlightedTrackId?: string;
  onOpenPlanner: (session: LearningPlanSession) => void;
  onDownstreamIntent: (intent: "continue_learning" | "start_review", trackId: string) => void;
};

export function LearningHomePage({
  user,
  refreshKey,
  highlightedTrackId,
  onOpenPlanner,
  onDownstreamIntent,
}: LearningHomePageProps) {
  const [tracks, setTracks] = useState<LearningTrackSummary[]>([]);
  const [currentSession, setCurrentSession] = useState<LearningPlanSession | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [startingPlanner, setStartingPlanner] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setStatus("loading");
    setErrorMessage(null);
    try {
      const [nextTracks, nextSession] = await Promise.all([
        fetchLearningTracks(user.id, signal),
        fetchCurrentLearningPlanSession(user.id, signal),
      ]);
      if (signal?.aborted) return;
      setTracks(nextTracks);
      setCurrentSession(nextSession);
      setStatus("ready");
    } catch (error) {
      if (signal?.aborted) return;
      setStatus("error");
      setErrorMessage(getErrorInfo(error).message);
    }
  }, [user.id]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, refreshKey]);

  async function startPlanner() {
    if (currentSession) {
      onOpenPlanner(currentSession);
      return;
    }
    setStartingPlanner(true);
    setErrorMessage(null);
    try {
      const session = await createLearningPlanSession({
        userId: user.id,
        clientActionId: createLearningActionId("learning-plan-session"),
      });
      setCurrentSession(session);
      onOpenPlanner(session);
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setStartingPlanner(false);
    }
  }

  return (
    <main className="learning-home" aria-labelledby="learning-home-title">
      <header className="learning-home-hero">
        <div>
          <p className="tutor-panel-eyebrow">你的学习主线</p>
          <h1 id="learning-home-title">今天从哪条主线继续？</h1>
          <p>进度、到期复习和运行能力均来自服务端权威状态。Aearn 不会在本地猜测掌握度或解锁条件。</p>
        </div>
      </header>

      {currentSession && (
        <section className="learning-plan-resume" aria-label="未完成的学习计划">
          <div><strong>你有一条未完成的学习计划</strong><span>会话和最新草案已由服务器保存，可以从上次位置继续。</span></div>
          <button className="tutor-primary-button" type="button" onClick={() => onOpenPlanner(currentSession)}>继续制定</button>
        </section>
      )}
      {errorMessage && <div className="tutor-inline-error" role="alert"><span>{errorMessage}</span><button className="tutor-text-button" type="button" onClick={() => void load()}>重试</button></div>}
      {status === "loading" && tracks.length === 0 && <p className="learning-home-status" role="status">正在读取学习主线……</p>}

      <section className="learning-track-grid" aria-label="LearningTrack 列表" aria-busy={status === "loading" || startingPlanner}>
        {tracks.map((track) => (
          <LearningTrackCard
            key={track.track_id}
            track={track}
            highlighted={track.track_id === highlightedTrackId}
            onContinue={() => onDownstreamIntent("continue_learning", track.track_id)}
            onReview={() => onDownstreamIntent("start_review", track.track_id)}
          />
        ))}
        <button className="learning-track-card learning-track-add" type="button" disabled={startingPlanner} onClick={() => void startPlanner()}>
          <span className="learning-track-add-icon" aria-hidden="true">＋</span>
          <strong>{currentSession ? "继续制定学习主线" : "添加学习语言 / 主线"}</strong>
          <span>{startingPlanner ? "正在进入计划对话……" : currentSession ? "从服务器保存的位置继续" : "在对话中确定语言、目标和学习节奏"}</span>
        </button>
      </section>
    </main>
  );
}

function LearningTrackCard({ track, highlighted, onContinue, onReview }: { track: LearningTrackSummary; highlighted: boolean; onContinue: () => void; onReview: () => void }) {
  return (
    <article className={highlighted ? "learning-track-card highlighted" : "learning-track-card"}>
      <header><span className="learning-track-language">{track.language_display_name}</span><span className={`learning-tier ${track.execution_tier}`}>{executionTierLabel(track.execution_tier)}</span></header>
      <div><h2>{track.active_plan_title}</h2><p>{track.goal_text}</p></div>
      <dl className="learning-track-facts">
        <div><dt>当前</dt><dd>{track.current_knowledge_title ?? "等待首个知识点"}</dd></div>
        <div><dt>阶段</dt><dd>{track.target_level}</dd></div>
        <div><dt>最近学习</dt><dd>{formatRelativeTime(track.last_learned_at)}</dd></div>
      </dl>
      <div className="learning-track-progress"><span><strong>{track.progress.percent}%</strong><small>{track.progress.completed} / {track.progress.total} 个知识点</small></span><progress max={100} value={track.progress.percent} aria-label={`${track.language_display_name} 路线进度`} /></div>
      <p className="learning-track-disclosure">{track.execution_disclosure}</p>
      <footer><button className="tutor-primary-button" type="button" onClick={onContinue}>继续学习</button>{track.review_due_count > 0 && <button className="tutor-compact-button quiet" type="button" onClick={onReview}>开始复习 · {track.review_due_count}</button>}</footer>
    </article>
  );
}

function executionTierLabel(value: LearningTrackSummary["execution_tier"]): string {
  return { teaching_local: "本地教学运行", container_verified: "容器已验证", static_only: "仅静态教学", unavailable: "不可执行" }[value];
}
function formatRelativeTime(value: string | null): string {
  if (!value) return "尚未开始";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间待同步" : date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function createLearningActionId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}:${random}`;
}
