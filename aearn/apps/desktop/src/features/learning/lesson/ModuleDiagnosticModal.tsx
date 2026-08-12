import { useEffect, useMemo, useRef, useState } from "react";

import {
  confirmModuleDiagnosticSkip,
  createModuleDiagnostic,
  createModuleDiagnosticAttempt,
  fetchModuleDiagnostic,
} from "../../../api";
import { getErrorInfo } from "../../../lib/errorMessages";
import type { ExerciseAttemptState, ModuleDiagnosticItem, ModuleDiagnosticState } from "../../../types";

type ModuleDiagnosticModalProps = {
  open: boolean;
  userId: string;
  trackId: string;
  moduleKey: string;
  trackVersion: number;
  onClose: () => void;
  onConfirmed: (state: ModuleDiagnosticState) => void;
};

type DiagnosticBusy = "starting" | "submitting" | "confirming" | null;

export function ModuleDiagnosticModal({
  open,
  userId,
  trackId,
  moduleKey,
  trackVersion,
  onClose,
  onConfirmed,
}: ModuleDiagnosticModalProps) {
  const [diagnostic, setDiagnostic] = useState<ModuleDiagnosticState | null>(null);
  const [editors, setEditors] = useState<Record<string, string>>({});
  const [pendingAttempt, setPendingAttempt] = useState<ExerciseAttemptState | null>(null);
  const [busy, setBusy] = useState<DiagnosticBusy>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) closeButtonRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && busy === null) onClose();
    }
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose, open]);

  useEffect(() => {
    if (!diagnostic) return;
    setEditors((current) => {
      const next = { ...current };
      for (const item of diagnostic.items) {
        if (next[item.item_id] === undefined) next[item.item_id] = starterText(item);
      }
      return next;
    });
  }, [diagnostic]);

  const currentItem = useMemo(
    () => diagnostic?.items.find((item) => item.result === null) ?? null,
    [diagnostic],
  );

  if (!open) return null;

  async function startDiagnostic() {
    if (busy !== null) return;
    setBusy("starting");
    setErrorMessage(null);
    try {
      const state = await createModuleDiagnostic({
        userId,
        trackId,
        moduleKey,
        expectedTrackVersion: trackVersion,
        clientActionId: createDiagnosticActionId("module-diagnostic-start"),
      });
      setDiagnostic(state);
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setBusy(null);
    }
  }

  async function submitCurrentItem() {
    if (!diagnostic || !currentItem || busy !== null) return;
    const submission = editors[currentItem.item_id] ?? "";
    if (!submission.trim()) return;
    setBusy("submitting");
    setErrorMessage(null);
    setPendingAttempt(null);
    try {
      const response = await createModuleDiagnosticAttempt({
        userId,
        trackId,
        moduleKey,
        sessionId: diagnostic.session_id,
        itemId: currentItem.item_id,
        submission,
        expectedTrackVersion: trackVersion,
        expectedSessionVersion: diagnostic.version,
        clientActionId: createDiagnosticActionId(`module-diagnostic-${currentItem.item_key}`),
      });
      if (isDiagnosticState(response)) {
        setDiagnostic(response);
        return;
      }
      setPendingAttempt(response);
      if (response.status === "pending") {
        const polled = await pollDiagnostic({
          userId,
          trackId,
          moduleKey,
          sessionId: diagnostic.session_id,
          previousVersion: diagnostic.version,
          itemId: currentItem.item_id,
        });
        if (polled) {
          setDiagnostic(polled);
          setPendingAttempt(null);
        }
      }
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setBusy(null);
    }
  }

  async function confirmSkip() {
    if (!diagnostic || diagnostic.state !== "passed_pending_confirmation" || busy !== null) return;
    setBusy("confirming");
    setErrorMessage(null);
    try {
      const confirmed = await confirmModuleDiagnosticSkip({
        userId,
        trackId,
        moduleKey,
        sessionId: diagnostic.session_id,
        expectedTrackVersion: diagnostic.impact?.expected_track_version ?? trackVersion,
        expectedSessionVersion: diagnostic.version,
        clientActionId: createDiagnosticActionId("module-diagnostic-confirm"),
      });
      setDiagnostic(confirmed);
      onConfirmed(confirmed);
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="module-diagnostic-overlay" onMouseDown={(event) => { if (event.currentTarget === event.target && busy === null) onClose(); }}>
      <section className="module-diagnostic-dialog" role="dialog" aria-modal="true" aria-labelledby="module-diagnostic-title">
        <header>
          <div>
            <p className="tutor-panel-eyebrow">模块边界诊断</p>
            <h2 id="module-diagnostic-title">申请跳过模块 · {moduleKey}</h2>
          </div>
          <button ref={closeButtonRef} className="tutor-compact-button quiet" type="button" disabled={busy !== null} onClick={onClose} aria-label="关闭模块诊断">关闭</button>
        </header>

        {!diagnostic ? (
          <div className="module-diagnostic-intro">
            <strong>这是独立诊断，不是单个知识点跳过。</strong>
            <p>服务器会冻结本模块全部核心能力和题目版本。只有所有核心能力都独立达到阈值，才会提出路线变更；仍需你再次确认才会生效。</p>
            <ul>
              <li>失败或部分通过不会跳过任何知识点。</li>
              <li>失败观察不会降低已经证明的掌握度。</li>
              <li>诊断中不提供提示或补救答案。</li>
            </ul>
            <button className="tutor-primary-button" type="button" disabled={busy !== null} onClick={() => void startDiagnostic()}>
              {busy === "starting" ? "正在冻结诊断版本……" : "开始独立诊断"}
            </button>
          </div>
        ) : (
          <DiagnosticBody
            diagnostic={diagnostic}
            currentItem={currentItem}
            editorValue={currentItem ? editors[currentItem.item_id] ?? "" : ""}
            pendingAttempt={pendingAttempt}
            busy={busy}
            onEditorChange={(value) => currentItem && setEditors((current) => ({ ...current, [currentItem.item_id]: value }))}
            onSubmit={() => void submitCurrentItem()}
            onConfirm={() => void confirmSkip()}
          />
        )}
        {errorMessage ? <p className="lesson-gate-error module-diagnostic-error" role="alert">{errorMessage}</p> : null}
      </section>
    </div>
  );
}

type DiagnosticBodyProps = {
  diagnostic: ModuleDiagnosticState;
  currentItem: ModuleDiagnosticItem | null;
  editorValue: string;
  pendingAttempt: ExerciseAttemptState | null;
  busy: DiagnosticBusy;
  onEditorChange: (value: string) => void;
  onSubmit: () => void;
  onConfirm: () => void;
};

function DiagnosticBody({ diagnostic, currentItem, editorValue, pendingAttempt, busy, onEditorChange, onSubmit, onConfirm }: DiagnosticBodyProps) {
  const completed = diagnostic.items.filter((item) => item.result !== null).length;
  return (
    <div className="module-diagnostic-body">
      <div className="module-diagnostic-progress">
        <div><strong>{completed} / {diagnostic.items.length}</strong><span>核心能力已检查</span></div>
        <div><strong>{Math.round(diagnostic.pass_threshold * 100)}%</strong><span>每项通过阈值</span></div>
        <div><strong>{diagnostic.independent_only ? "独立" : "允许辅助"}</strong><span>完成要求</span></div>
      </div>

      <ol className="module-diagnostic-items" aria-label="诊断能力列表">
        {diagnostic.items.map((item) => (
          <li key={item.item_id} className={item.result?.outcome === "passed" ? "passed" : item.result ? "failed" : item.item_id === currentItem?.item_id ? "current" : "pending"}>
            <span>{item.order_index + 1}</span>
            <div><strong>{item.capability_key}</strong><small>{item.result ? `${diagnosticOutcomeLabel(item.result.outcome)} · ${Math.round(item.result.score * 100)}%` : item.item_id === currentItem?.item_id ? "当前题目" : "等待前置题目"}</small></div>
          </li>
        ))}
      </ol>

      {diagnostic.state === "active" && currentItem ? (
        <section className="module-diagnostic-question" aria-labelledby={`diagnostic-item-${currentItem.item_id}`}>
          <p className="tutor-panel-eyebrow">核心能力 {currentItem.order_index + 1}</p>
          <h3 id={`diagnostic-item-${currentItem.item_id}`}>{currentItem.exercise.title}</h3>
          <p>{promptText(currentItem)}</p>
          <label>
            <span>独立作答</span>
            <textarea rows={Math.min(15, Math.max(8, editorValue.split("\n").length + 2))} value={editorValue} spellCheck={false} disabled={busy !== null} onChange={(event) => onEditorChange(event.target.value)} />
          </label>
          <button className="tutor-primary-button" type="button" disabled={busy !== null || !editorValue.trim()} onClick={onSubmit}>
            {busy === "submitting" ? "正在提交诊断……" : "提交当前能力检查"}
          </button>
          {pendingAttempt?.status === "pending" ? <p className="module-diagnostic-pending" role="status">受控执行仍在队列中，正在读取同一 Attempt 的结果……</p> : null}
        </section>
      ) : null}

      {diagnostic.state === "failed" ? (
        <section className="module-diagnostic-decision failed" role="status">
          <p className="tutor-panel-eyebrow">本次诊断未通过</p>
          <h3>未跳过任何知识点</h3>
          <p>服务器只记录了不降低既有掌握度的观察证据。可以按薄弱能力继续学习，冷却期结束后再重新申请。</p>
          {diagnostic.weak_capabilities.length > 0 ? <p><strong>建议优先补强：</strong>{diagnostic.weak_capabilities.join("、")}</p> : null}
          {diagnostic.cooldown_until ? <small>下一次可申请时间由服务器记录：{formatTime(diagnostic.cooldown_until)}</small> : null}
        </section>
      ) : null}

      {diagnostic.state === "passed_pending_confirmation" ? (
        <section className="module-diagnostic-decision passed" role="status">
          <p className="tutor-panel-eyebrow">全部核心能力已通过</p>
          <h3>路线变更尚未生效</h3>
          <p>服务器已生成 predecessor-linked successor revision。确认后，以下知识点才会标记为 diagnostic_skipped：</p>
          <ul>{diagnostic.impact?.affected_knowledge_keys.map((key) => <li key={key}>{key}</li>)}</ul>
          <button className="tutor-primary-button" type="button" disabled={busy !== null} onClick={onConfirm}>
            {busy === "confirming" ? "正在激活新路线……" : "确认跳过整个模块"}
          </button>
        </section>
      ) : null}

      {diagnostic.state === "confirmed" ? (
        <section className="module-diagnostic-decision confirmed" role="status">
          <p className="tutor-panel-eyebrow">路线已更新</p>
          <h3>模块已按诊断结果跳过</h3>
          <p>服务端已激活 successor revision，并重新计算下游可用性。关闭后返回学习主线即可查看新位置。</p>
        </section>
      ) : null}

      {diagnostic.state === "expired" ? (
        <section className="module-diagnostic-decision failed" role="status"><h3>诊断已过期</h3><p>此会话不再接受提交，请关闭后重新申请。</p></section>
      ) : null}
    </div>
  );
}

async function pollDiagnostic(input: {
  userId: string;
  trackId: string;
  moduleKey: string;
  sessionId: string;
  previousVersion: number;
  itemId: string;
}): Promise<ModuleDiagnosticState | null> {
  for (let index = 0; index < 24; index += 1) {
    await new Promise((resolve) => globalThis.setTimeout(resolve, 850));
    const state = await fetchModuleDiagnostic(input.userId, input.trackId, input.moduleKey, input.sessionId);
    if (state.version !== input.previousVersion || state.state !== "active" || state.items.find((item) => item.item_id === input.itemId)?.result) return state;
  }
  return null;
}

function isDiagnosticState(value: ExerciseAttemptState | ModuleDiagnosticState): value is ModuleDiagnosticState {
  return "session_id" in value;
}

function starterText(item: ModuleDiagnosticItem): string {
  if (item.exercise.exercise_type === "model_code_review") return "";
  const value = item.exercise.starter_artifact.content;
  return typeof value === "string" ? value : "";
}

function promptText(item: ModuleDiagnosticItem): string {
  if (item.exercise.exercise_type === "model_code_review") return item.exercise.learner_prompt.learner_instruction;
  const value = item.exercise.learner_prompt.text;
  return typeof value === "string" ? value : `请完成 ${item.capability_key} 的独立能力检查。`;
}

function diagnosticOutcomeLabel(outcome: ModuleDiagnosticItem["result"] extends infer _ ? "passed" | "failed" | "timed_out" | "cancelled" | "unavailable" | "invalid" : never): string {
  return {
    passed: "通过",
    failed: "未通过",
    timed_out: "超时",
    cancelled: "已取消",
    unavailable: "不可用",
    invalid: "无效",
  }[outcome];
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

function createDiagnosticActionId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}:${random}`;
}
