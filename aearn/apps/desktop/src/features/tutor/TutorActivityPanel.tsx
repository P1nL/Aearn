import { useState } from "react";

import type { TutorActivityItem, TutorInboxItem } from "../../types";

type TutorActivityPanelProps = {
  activity: TutorActivityItem[];
  inbox: TutorInboxItem[];
  loading: boolean;
  errorMessage: string | null;
  busyInboxId: string | null;
  onRetry: () => void;
  onMarkRead: (inboxId: string) => Promise<void>;
  onDismiss: (inboxId: string) => Promise<void>;
};

export function TutorActivityPanel({
  activity,
  inbox,
  loading,
  errorMessage,
  busyInboxId,
  onRetry,
  onMarkRead,
  onDismiss,
}: TutorActivityPanelProps) {
  const [actionError, setActionError] = useState<string | null>(null);

  async function handleInboxAction(action: "read" | "dismiss", inboxId: string) {
    setActionError(null);
    try {
      if (action === "read") {
        await onMarkRead(inboxId);
      } else {
        await onDismiss(inboxId);
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "收件箱操作失败，请重试。");
    }
  }

  return (
    <section className="tutor-panel tutor-activity-panel" aria-labelledby="tutor-activity-title">
      <div className="tutor-panel-heading">
        <div>
          <p className="tutor-panel-eyebrow">学习动态</p>
          <h2 id="tutor-activity-title">最近发生的事</h2>
        </div>
        <button className="tutor-text-button" type="button" onClick={onRetry} disabled={loading}>
          刷新
        </button>
      </div>

      {errorMessage && (
        <div className="tutor-inline-error" role="alert">
          <span>{errorMessage}</span>
          <button className="tutor-text-button" type="button" onClick={onRetry}>重试</button>
        </div>
      )}

      <div className="tutor-inbox" aria-label="学习提醒">
        <h3>学习提醒</h3>
        {loading && inbox.length === 0 && <p className="tutor-muted-copy">正在读取提醒……</p>}
        {!loading && inbox.length === 0 && <p className="tutor-muted-copy">暂时没有需要处理的提醒。</p>}
        {inbox.map((item) => {
          const isBusy = busyInboxId === item.inbox_id;
          return (
            <article className="tutor-inbox-item" key={item.inbox_id}>
              <div>
                <p>{item.message}</p>
                <span>{formatTutorTime(item.created_at)}</span>
              </div>
              {item.state === "unread" ? (
                <div className="tutor-inbox-actions">
                  <button type="button" className="tutor-compact-button" disabled={isBusy} onClick={() => void handleInboxAction("read", item.inbox_id)}>
                    标为已读
                  </button>
                  <button type="button" className="tutor-compact-button quiet" disabled={isBusy} onClick={() => void handleInboxAction("dismiss", item.inbox_id)}>
                    忽略
                  </button>
                </div>
              ) : (
                <span className="tutor-state-label">已读</span>
              )}
            </article>
          );
        })}
      </div>

      {actionError && <p className="tutor-action-error" role="alert">{actionError}</p>}

      <div className="tutor-activity-list" aria-label="活动时间线">
        <h3>活动记录</h3>
        {loading && activity.length === 0 && <p className="tutor-muted-copy">正在读取活动……</p>}
        {!loading && activity.length === 0 && <p className="tutor-muted-copy">完成一次 Tutor 操作后，学习活动会显示在这里。</p>}
        {activity.map((item) => (
          <article className="tutor-activity-item" key={item.activity_id}>
            <span className="tutor-activity-dot" aria-hidden="true" />
            <div>
              <strong>{displayActivityCategory(item.category)}</strong>
              <p>{item.reason}</p>
              <span>{formatTutorTime(item.created_at)}{item.evidence.length > 0 ? ` · ${item.evidence.length} 条依据` : ""}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function displayActivityCategory(category: string): string {
  if (category.includes("plan")) return "学习计划更新";
  if (category.includes("memory")) return "学习记录更新";
  if (category.includes("runner")) return "练习反馈";
  return "学习活动";
}

function formatTutorTime(value: string | null): string {
  if (!value) return "时间待同步";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
