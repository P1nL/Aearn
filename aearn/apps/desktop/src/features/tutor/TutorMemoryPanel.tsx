import { useState } from "react";

import type { TutorMemoryItem } from "../../types";

type TutorMemoryPanelProps = {
  memory: TutorMemoryItem[];
  loading: boolean;
  errorMessage: string | null;
  busyEntryId: string | null;
  onRetry: () => void;
  onCorrect: (entryId: string, statement: string) => Promise<void>;
  onDelete: (entryId: string) => Promise<void>;
};

export function TutorMemoryPanel({
  memory,
  loading,
  errorMessage,
  busyEntryId,
  onRetry,
  onCorrect,
  onDelete,
}: TutorMemoryPanelProps) {
  const [editingEntryId, setEditingEntryId] = useState<string | null>(null);
  const [draftStatement, setDraftStatement] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  function startEditing(entry: TutorMemoryItem) {
    setActionError(null);
    setEditingEntryId(entry.entry_id);
    setDraftStatement(entry.statement);
  }

  async function saveCorrection(entryId: string) {
    const statement = draftStatement.trim();
    if (!statement) {
      setActionError("更正内容不能为空。");
      return;
    }
    setActionError(null);
    try {
      await onCorrect(entryId, statement);
      setEditingEntryId(null);
      setDraftStatement("");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "记忆更正失败，请重试。");
    }
  }

  async function removeEntry(entryId: string) {
    setActionError(null);
    try {
      await onDelete(entryId);
      if (editingEntryId === entryId) {
        setEditingEntryId(null);
        setDraftStatement("");
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "记忆删除失败，请重试。");
    }
  }

  return (
    <section className="tutor-panel tutor-memory-panel" aria-labelledby="tutor-memory-title">
      <div className="tutor-panel-heading">
        <div>
          <p className="tutor-panel-eyebrow">可检查的学习记录</p>
          <h2 id="tutor-memory-title">我记住了什么</h2>
        </div>
        <button className="tutor-text-button" type="button" onClick={onRetry} disabled={loading}>刷新</button>
      </div>

      <p className="tutor-panel-description">这里仅显示可核对、可更正或删除的学习记录，不展示模型、提示词或诊断细节。</p>
      {errorMessage && (
        <div className="tutor-inline-error" role="alert">
          <span>{errorMessage}</span>
          <button className="tutor-text-button" type="button" onClick={onRetry}>重试</button>
        </div>
      )}
      {actionError && <p className="tutor-action-error" role="alert">{actionError}</p>}

      {loading && memory.length === 0 && <p className="tutor-muted-copy">正在读取学习记录……</p>}
      {!loading && memory.length === 0 && <p className="tutor-muted-copy">还没有可展示的学习记录。</p>}

      <div className="tutor-memory-list">
        {memory.map((entry) => {
          const isEditing = editingEntryId === entry.entry_id;
          const isBusy = busyEntryId === entry.entry_id;
          return (
            <article className="tutor-memory-entry" key={entry.entry_id}>
              <div className="tutor-memory-meta">
                <span className={`tutor-kind-tag ${entry.memory_kind}`}>{entry.memory_kind === "objective_fact" ? "已验证事实" : "学习推断"}</span>
                {entry.confidence && <span>可信度：{entry.confidence}</span>}
                <span>来源：{entry.provenance}</span>
              </div>
              {isEditing ? (
                <form className="tutor-memory-editor" onSubmit={(event) => { event.preventDefault(); void saveCorrection(entry.entry_id); }}>
                  <label htmlFor={`tutor-memory-${entry.entry_id}`}>更正后的表述</label>
                  <textarea
                    id={`tutor-memory-${entry.entry_id}`}
                    value={draftStatement}
                    maxLength={180}
                    rows={3}
                    disabled={isBusy}
                    onChange={(event) => setDraftStatement(event.target.value)}
                  />
                  <div className="tutor-inline-actions">
                    <button className="tutor-compact-button" type="submit" disabled={isBusy || draftStatement.trim().length === 0}>保存更正</button>
                    <button className="tutor-compact-button quiet" type="button" disabled={isBusy} onClick={() => setEditingEntryId(null)}>取消</button>
                  </div>
                </form>
              ) : (
                <p className="tutor-memory-statement">{entry.statement}</p>
              )}
              <dl className="tutor-memory-details">
                <div><dt>记录类型</dt><dd>{entry.category}</dd></div>
                <div><dt>依据</dt><dd>{entry.evidence.length > 0 ? entry.evidence.join(" · ") : "暂未提供"}</dd></div>
                <div><dt>保留至</dt><dd>{formatTutorTime(entry.retention_until)}</dd></div>
                <div><dt>复核时间</dt><dd>{formatTutorTime(entry.stale_after)}</dd></div>
              </dl>
              <div className="tutor-inline-actions">
                <button className="tutor-compact-button" type="button" disabled={isBusy || isEditing} onClick={() => startEditing(entry)}>更正</button>
                <button className="tutor-compact-button quiet danger" type="button" disabled={isBusy} onClick={() => void removeEntry(entry.entry_id)}>删除</button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function formatTutorTime(value: string | null): string {
  if (!value) return "未设置";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { year: "numeric", month: "numeric", day: "numeric" });
}
