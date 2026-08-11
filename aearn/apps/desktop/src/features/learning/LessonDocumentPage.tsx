import { useCallback, useEffect, useState } from "react";

import {
  activateLessonMigration,
  createLessonGateAttempt,
  fetchExerciseAttempt,
  fetchLessonDocument,
  fetchLessonGates,
  prepareLessonDocument,
  prepareLessonGate,
  requestLessonGateHint,
  startLessonDocument,
} from "../../api";
import { getErrorInfo } from "../../lib/errorMessages";
import type {
  ExerciseAttemptState,
  LessonDocumentState,
  LessonExerciseGateBlock,
  LessonGateHint,
  LessonGateItem,
  LessonGateList,
  ModuleDiagnosticState,
} from "../../types";
import { LessonDocumentView } from "./lesson/LessonDocumentView";
import { LessonGatePanel } from "./lesson/LessonGatePanel";
import { ModuleDiagnosticModal } from "./lesson/ModuleDiagnosticModal";

type LessonDocumentPageProps = {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  onBack: () => void;
};

type LessonAction = "idle" | "preparing" | "starting" | "refreshing" | "migrating";
type GateAction = "prepare" | "hint" | "run" | "submit" | "poll";

type BusyGate = {
  gateKey: string;
  action: GateAction;
};

export function LessonDocumentPage({ userId, trackId, knowledgeKey, onBack }: LessonDocumentPageProps) {
  const [state, setState] = useState<LessonDocumentState | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<LessonAction>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [gates, setGates] = useState<LessonGateList | null>(null);
  const [gateLoading, setGateLoading] = useState(false);
  const [gateLoadError, setGateLoadError] = useState<string | null>(null);
  const [gateEditors, setGateEditors] = useState<Record<string, string>>({});
  const [gateHints, setGateHints] = useState<Record<string, LessonGateHint | null>>({});
  const [gateAttempts, setGateAttempts] = useState<Record<string, ExerciseAttemptState | null>>({});
  const [gateStale, setGateStale] = useState<Record<string, boolean>>({});
  const [gateErrors, setGateErrors] = useState<Record<string, string | null>>({});
  const [busyGate, setBusyGate] = useState<BusyGate | null>(null);
  const [diagnosticOpen, setDiagnosticOpen] = useState(false);

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

  const loadGates = useCallback(async (signal?: AbortSignal) => {
    setGateLoading(true);
    setGateLoadError(null);
    try {
      const next = await fetchLessonGates(userId, trackId, knowledgeKey, signal);
      if (signal?.aborted) return;
      setGates(next);
      setGateEditors((current) => initializeGateEditors(current, next.items));
    } catch (error) {
      if (!signal?.aborted) setGateLoadError(getErrorInfo(error).message);
    } finally {
      if (!signal?.aborted) setGateLoading(false);
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

  useEffect(() => {
    if (state?.status !== "ready" || !state.assignment) {
      setGates(null);
      return undefined;
    }
    const controller = new AbortController();
    void loadGates(controller.signal);
    return () => controller.abort();
  }, [loadGates, state?.assignment, state?.status]);

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
      await Promise.all([load(), loadGates()]);
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
      await Promise.all([load(), loadGates()]);
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setAction("idle");
    }
  }

  async function prepareGateAction(block: LessonExerciseGateBlock) {
    if (!gates || busyGate) return;
    setBusyGate({ gateKey: block.gate_key, action: "prepare" });
    setGateError(block.gate_key, null);
    try {
      await prepareLessonGate({
        userId,
        trackId,
        knowledgeKey,
        gateKey: block.gate_key,
        expectedTrackVersion: gates.track_version,
        expectedProgressVersion: gates.progress_version,
        clientActionId: createLessonActionId(`gate-prepare-${block.gate_key}`),
      });
      await loadGates();
    } catch (error) {
      setGateError(block.gate_key, getErrorInfo(error).message);
    } finally {
      setBusyGate(null);
    }
  }

  async function hintGateAction(block: LessonExerciseGateBlock) {
    const gate = boundGate(block.gate_key);
    if (!gate || busyGate) return;
    setBusyGate({ gateKey: block.gate_key, action: "hint" });
    setGateError(block.gate_key, null);
    try {
      const hint = await requestLessonGateHint({
        userId,
        trackId,
        knowledgeKey,
        gateKey: block.gate_key,
        expectedGateVersion: gate.gate_version,
        clientActionId: createLessonActionId(`gate-hint-${block.gate_key}`),
      });
      setGateHints((current) => ({ ...current, [block.gate_key]: hint }));
      await loadGates();
    } catch (error) {
      setGateError(block.gate_key, getErrorInfo(error).message);
    } finally {
      setBusyGate(null);
    }
  }

  async function attemptGateAction(block: LessonExerciseGateBlock, attemptType: "run" | "submit") {
    const gate = boundGate(block.gate_key);
    if (!gate || !gates || busyGate) return;
    const submission = gateEditors[block.gate_key] ?? "";
    if (!submission.trim()) return;
    setBusyGate({ gateKey: block.gate_key, action: attemptType });
    setGateError(block.gate_key, null);
    setGateStale((current) => ({ ...current, [block.gate_key]: false }));
    try {
      let attempt = await createLessonGateAttempt({
        userId,
        trackId,
        knowledgeKey,
        gateKey: block.gate_key,
        attemptType,
        submission,
        expectedTrackVersion: gates.track_version,
        expectedProgressVersion: gates.progress_version,
        expectedAssignmentVersion: gates.assignment_version,
        expectedGateVersion: gate.gate_version,
        clientActionId: createLessonActionId(`gate-${attemptType}-${block.gate_key}`),
      });
      setGateAttempts((current) => ({ ...current, [block.gate_key]: attempt }));
      if (attempt.status === "pending") {
        attempt = await pollExerciseAttempt({ userId, trackId, knowledgeKey, attemptId: attempt.attempt_id });
        setGateAttempts((current) => ({ ...current, [block.gate_key]: attempt }));
        if (attempt.status === "pending") setGateError(block.gate_key, "受控执行仍在队列中，可以稍后刷新同一 Attempt 的结果。");
      }
      await Promise.all([load(), loadGates()]);
    } catch (error) {
      setGateError(block.gate_key, getErrorInfo(error).message);
    } finally {
      setBusyGate(null);
    }
  }

  async function pollGateAttempt(block: LessonExerciseGateBlock) {
    const currentAttempt = gateAttempts[block.gate_key];
    if (!currentAttempt || currentAttempt.status !== "pending" || busyGate) return;
    setBusyGate({ gateKey: block.gate_key, action: "poll" });
    setGateError(block.gate_key, null);
    try {
      const attempt = await pollExerciseAttempt({
        userId,
        trackId,
        knowledgeKey,
        attemptId: currentAttempt.attempt_id,
      });
      setGateAttempts((current) => ({ ...current, [block.gate_key]: attempt }));
      if (attempt.status === "pending") setGateError(block.gate_key, "受控执行仍在队列中，稍后可继续刷新同一 Attempt。");
      await Promise.all([load(), loadGates()]);
    } catch (error) {
      setGateError(block.gate_key, getErrorInfo(error).message);
    } finally {
      setBusyGate(null);
    }
  }

  function boundGate(gateKey: string) {
    const gate = gates?.items.find((item) => item.gate_key === gateKey);
    return gate && gate.status !== "unbound" ? gate : null;
  }

  function setGateError(gateKey: string, message: string | null) {
    setGateErrors((current) => ({ ...current, [gateKey]: message }));
  }

  function updateGateEditor(gateKey: string, value: string) {
    setGateEditors((current) => ({ ...current, [gateKey]: value }));
    if (gateAttempts[gateKey]?.result) setGateStale((current) => ({ ...current, [gateKey]: true }));
  }

  function renderExerciseGate(block: LessonExerciseGateBlock) {
    const gate = gates?.items.find((item) => item.gate_key === block.gate_key) ?? null;
    const currentBusy = busyGate?.gateKey === block.gate_key ? busyGate.action : null;
    return (
      <LessonGatePanel
        key={block.block_id}
        block={block}
        gate={gate}
        editorValue={gateEditors[block.gate_key] ?? ""}
        hint={gateHints[block.gate_key] ?? null}
        attempt={gateAttempts[block.gate_key] ?? null}
        resultStale={gateStale[block.gate_key] ?? false}
        busyAction={currentBusy}
        errorMessage={gateErrors[block.gate_key] ?? null}
        onEditorChange={(value) => updateGateEditor(block.gate_key, value)}
        onPrepare={() => void prepareGateAction(block)}
        onHint={() => void hintGateAction(block)}
        onRun={() => void attemptGateAction(block, "run")}
        onSubmit={() => void attemptGateAction(block, "submit")}
        onPoll={() => void pollGateAttempt(block)}
      />
    );
  }

  async function handleDiagnosticConfirmed(_diagnostic: ModuleDiagnosticState) {
    await Promise.all([load(), loadGates()]);
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
          {state.module_diagnostic_allowed ? (
            <section className="lesson-module-diagnostic-entry" aria-label="模块跳过诊断">
              <div><p className="tutor-panel-eyebrow">模块边界 · {state.module_key}</p><h2>已经掌握本模块？</h2><p>可以申请一次覆盖全部核心能力的独立诊断。部分通过不会跳过任何知识点。</p></div>
              <button className="tutor-compact-button quiet" type="button" onClick={() => setDiagnosticOpen(true)}>申请跳过模块</button>
            </section>
          ) : null}
          {state.update && <LessonUpdateNotice state={state} busy={action === "migrating"} onMigrate={() => void migrate()} />}
          {gateLoadError ? <div className="tutor-inline-error lesson-page-error" role="alert"><span>{gateLoadError}</span><button className="tutor-text-button" type="button" disabled={gateLoading} onClick={() => void loadGates()}>{gateLoading ? "正在读取……" : "重新读取练习"}</button></div> : null}
          <LessonDocumentView document={state.document} assignment={state.assignment} sources={state.sources} renderExerciseGate={renderExerciseGate} />
          <ModuleDiagnosticModal
            open={diagnosticOpen}
            userId={userId}
            trackId={trackId}
            moduleKey={state.module_key}
            trackVersion={state.track_version}
            onClose={() => setDiagnosticOpen(false)}
            onConfirmed={(diagnostic) => void handleDiagnosticConfirmed(diagnostic)}
          />
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

function initializeGateEditors(current: Record<string, string>, items: LessonGateItem[]): Record<string, string> {
  const next = { ...current };
  for (const item of items) {
    if (item.status === "unbound" || next[item.gate_key] !== undefined) continue;
    const starter = item.exercise.starter_artifact.content;
    next[item.gate_key] = typeof starter === "string" ? starter : "";
  }
  return next;
}

async function pollExerciseAttempt(input: { userId: string; trackId: string; knowledgeKey: string; attemptId: string }): Promise<ExerciseAttemptState> {
  let latest = await fetchExerciseAttempt(input.userId, input.trackId, input.knowledgeKey, input.attemptId);
  for (let index = 0; latest.status === "pending" && index < 24; index += 1) {
    await new Promise((resolve) => globalThis.setTimeout(resolve, 850));
    latest = await fetchExerciseAttempt(input.userId, input.trackId, input.knowledgeKey, input.attemptId);
  }
  return latest;
}

function createLessonActionId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}:${random}`;
}
