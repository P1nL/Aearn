import { useCallback, useEffect, useState } from "react";

import {
  activateLessonMigration,
  fetchLessonDocument,
  prepareLessonDocument,
  startLessonDocument,
} from "../../api";
import { getErrorInfo } from "../../lib/errorMessages";
import type { LessonDocumentState } from "../../types";
import { LessonDocumentView } from "./lesson/LessonDocumentView";

type LessonDocumentPageProps = {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  onBack: () => void;
};

type LessonAction = "idle" | "preparing" | "starting" | "refreshing" | "migrating";

export function LessonDocumentPage({ userId, trackId, knowledgeKey, onBack }: LessonDocumentPageProps) {
  const [state, setState] = useState<LessonDocumentState | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<LessonAction>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setErrorMessage(null);
    try {
      const next = await fetchLessonDocument(userId, trackId, knowledgeKey, signal);
      if (!signal?.aborted) setState(next);
    } catch (error) {
      if (!signal?.aborted) setErrorMessage(getErrorInfo(error).message);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [knowledgeKey, trackId, userId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    if (state?.status !== "preparing") return undefined;
    const timer = globalThis.setInterval(() => void load(), 1400);
    return () => globalThis.clearInterval(timer);
  }, [load, state?.status]);

  async function prepare(refresh: boolean) {
    if (!state || action !== "idle") return;
    setAction(refresh ? "refreshing" : "preparing");
    setErrorMessage(null);
    try {
      await prepareLessonDocument({
        userId,
        trackId,
        knowledgeKey,
        expectedTrackVersion: state.track_version,
        expectedProgressVersion: state.progress_version,
        clientActionId: createLessonActionId(refresh ? "lesson-refresh" : "lesson-prepare"),
        refresh,
      });
      await load();
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setAction("idle");
    }
  }

  async function start() {
    if (!state?.assignment || action !== "idle") return;
    setAction("starting");
    setErrorMessage(null);
    try {
      await startLessonDocument({
        userId,
        trackId,
        knowledgeKey,
        assignmentId: state.assignment.assignment_id,
        expectedAssignmentVersion: state.assignment.assignment_version,
        expectedProgressVersion: state.progress_version,
        clientActionId: createLessonActionId("lesson-start"),
      });
      await load();
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setAction("idle");
    }
  }

  async function migrate() {
    if (!state?.update || action !== "idle") return;
    setAction("migrating");
    setErrorMessage(null);
    try {
      await activateLessonMigration({
        userId,
        trackId,
        knowledgeKey,
        assignmentId: state.update.assignment_id,
        expectedAssignmentVersion: state.update.assignment_version,
        clientActionId: createLessonActionId("lesson-migrate"),
      });
      await load();
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setAction("idle");
    }
  }

  return (
    <main className="lesson-page" aria-labelledby="lesson-page-title">
      <header className="lesson-page-toolbar">
        <button className="tutor-text-button" type="button" onClick={onBack}>← 返回学习主线</button>
        <div><span>{knowledgeKey}</span><strong id="lesson-page-title">课程阅读</strong></div>
        {state?.status === "ready" && <button className="tutor-compact-button quiet" type="button" disabled={action !== "idle"} onClick={() => void prepare(true)}>{action === "refreshing" ? "正在检查更新……" : "检查课程更新"}</button>}
      </header>

      {errorMessage && <div className="tutor-inline-error lesson-page-error" role="alert"><span>{errorMessage}</span><button className="tutor-text-button" type="button" onClick={() => void load()}>重新读取</button></div>}
      {loading && !state && <LessonStatus title="正在读取课程 authority" body="服务器正在核对 assignment、来源快照与当前进度。" />}
      {!loading && state?.status === "missing" && <LessonStatus title="课程尚未准备" body="进入本页不会使用临时聊天内容。点击后，服务器会从已登记的受信来源生成并冻结结构化课程。" actionLabel={action === "preparing" ? "正在创建……" : "准备课程"} disabled={action !== "idle"} onAction={() => void prepare(false)} />}
      {state?.status === "preparing" && <LessonStatus title="正在生成可追溯课程" body="课程生成在短事务之外运行；完成后本页会自动读取 immutable document、assignment 与来源快照。" busy />}
      {state?.status === "failed" && <LessonStatus title="课程准备未完成" body={state.authoring_run?.failure_message ?? "课程生成失败，没有发布半成品或无来源模板。"} detail={state.authoring_run?.failure_code ?? undefined} actionLabel={action === "preparing" ? "正在重试……" : "重试准备"} disabled={action !== "idle"} onAction={() => void prepare(false)} />}
      {state?.status === "ready" && state.document && state.assignment && (
        <>
          <section className="lesson-version-actions" aria-label="课程版本状态">
            <div><strong>{state.assignment.started_at ? "当前版本已冻结" : "开始后冻结当前版本"}</strong><span>{state.assignment.started_at ? "来源、正文顺序和 Gate contract 不会被后台更新静默替换。" : "开始只推进到 in_progress，不会写完成、掌握度或解锁事实。"}</span></div>
            {!state.assignment.started_at && <button className="tutor-primary-button" type="button" disabled={action !== "idle"} onClick={() => void start()}>{action === "starting" ? "正在开始……" : "开始本课"}</button>}
          </section>
          {state.update && <LessonUpdateNotice state={state} busy={action === "migrating"} onMigrate={() => void migrate()} />}
          <LessonDocumentView document={state.document} assignment={state.assignment} sources={state.sources} />
        </>
      )}
    </main>
  );
}

function LessonStatus({ title, body, detail, actionLabel, disabled, onAction, busy = false }: { title: string; body: string; detail?: string; actionLabel?: string; disabled?: boolean; onAction?: () => void; busy?: boolean }) {
  return <section className="lesson-status" aria-live="polite" aria-busy={busy}><span className={busy ? "lesson-status-pulse" : "lesson-status-icon"} aria-hidden="true">{busy ? "" : "↗"}</span><div><p className="tutor-panel-eyebrow">LessonDocument</p><h1>{title}</h1><p>{body}</p>{detail && <code>{detail}</code>}{actionLabel && onAction && <button className="tutor-primary-button" type="button" disabled={disabled} onClick={onAction}>{actionLabel}</button>}</div></section>;
}

function LessonUpdateNotice({ state, busy, onMigrate }: { state: LessonDocumentState; busy: boolean; onMigrate: () => void }) {
  const update = state.update;
  if (!update) return null;
  const changed = update.impact.source_changes.length + update.impact.blocks_added.length + update.impact.blocks_removed.length + update.impact.blocks_reordered.length + update.impact.examples_changed.length + update.impact.gates_changed.length;
  return <section className="lesson-update-notice"><div><p className="tutor-panel-eyebrow">有新课程版本</p><h2>更新不会自动替换已开始课程</h2><p>{changed > 0 ? `检测到 ${changed} 组来源或内容影响。` : "新版本保留当前结构，但生成 lineage 已更新。"} 当前文档会一直保持 active，直到你明确迁移。</p></div><button className="tutor-primary-button" type="button" disabled={busy} onClick={onMigrate}>{busy ? "正在迁移……" : "查看影响后迁移"}</button></section>;
}

function createLessonActionId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}:${random}`;
}
