import { useState } from "react";

import type { HarnessCutoverDecision, UserProfile } from "../types";

type HarnessCutoverPageProps = {
  user: UserProfile | null;
  decision: HarnessCutoverDecision | null;
  actionState: "idle" | "loading" | "success" | "error";
  actionMessage: string | null;
  onConfirm: () => Promise<boolean>;
  onRefresh: () => Promise<void>;
};

const categoryLabels: Record<string, string> = {
  learning_plans: "学习路线",
  plan_modules: "学习模块",
  knowledge_points: "知识点状态",
  exercises: "生成练习",
  code_blanks: "练习填空",
  test_cases: "练习测试记录",
  teaching_chunks: "讲解片段",
  learning_sessions: "学习会话",
  attempts: "练习结果",
  review_states: "复习状态",
  review_logs: "复习记录",
  review_seed_banks: "复习候选记录",
  exercise_variant_cache: "练习变体缓存",
  notes: "学习笔记",
  onboarding_conversations: "建档对话",
  onboarding_messages: "建档消息",
  learning_messages: "学习对话消息",
  review_messages: "复习对话消息",
  learner_profiles: "学习者画像",
  idempotency_records: "旧流程重试记录",
};

const profileFieldLabels: Record<string, string> = {
  learning_style: "学习风格",
  teaching_preference: "讲解偏好",
  encouragement_preference: "反馈偏好",
  profession: "职业信息",
  background_context: "背景补充",
};

export function HarnessCutoverPage({
  user,
  decision,
  actionState,
  actionMessage,
  onConfirm,
  onRefresh,
}: HarnessCutoverPageProps) {
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const summary = decision?.summary;
  const isReady = decision?.state === "summary_ready";
  const blocked = decision?.state === "blocked_target_state" || decision?.state === "blocked_checkpoint_scope";

  async function handleConfirm() {
    if (!isReady || !confirmed || pending) return;
    setPending(true);
    try {
      await onConfirm();
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="harness-cutover-page" aria-labelledby="harness-cutover-title">
      <section className="harness-cutover-card">
        <header className="harness-cutover-header">
          <p className="harness-cutover-eyebrow">Aearn Tutor 切换</p>
          <h1 id="harness-cutover-title">先完成一次受控清理</h1>
          <p>
            {user?.display_name ? `${user.display_name}，` : ""}
            新 Tutor 会从一个干净的学习入口开始。旧学习记录不会迁移；服务器会在确认前重新核对范围。
          </p>
        </header>

        {blocked ? (
          <section className="harness-cutover-blocked" role="alert" aria-live="polite">
            <h2>{blockedTitle(decision?.code)}</h2>
            <p>{blockedMessage(decision?.code)}</p>
            <p className="harness-cutover-muted">没有删除旧学习记录，也没有删除已有 Tutor 数据。两种学习入口都会保持锁定。</p>
            <button className="harness-cutover-secondary" type="button" disabled={pending} onClick={() => void onRefresh()}>
              重新检查
            </button>
          </section>
        ) : isReady ? (
          <>
            <section className="harness-cutover-summary" aria-labelledby="cutover-delete-title">
              <div>
                <h2 id="cutover-delete-title">将被清理的旧学习记录</h2>
                <p>以下摘要由服务器生成。确认时会再次核对；如果记录已变化，系统会要求你查看新的摘要。</p>
              </div>
              <ul className="harness-cutover-counts">
                {summary?.legacy_categories.map((category) => (
                  <li key={category.id}>
                    <span>{categoryLabels[category.id] ?? category.id}</span>
                    <strong>{category.count}</strong>
                  </li>
                ))}
                {summary?.legacy_profile_fields.map((field) => (
                  <li key={field.id}>
                    <span>{profileFieldLabels[field.id] ?? field.id}</span>
                    <strong>清空</strong>
                  </li>
                ))}
              </ul>
              {summary?.checkpoint.record_count ? (
                <p className="harness-cutover-checkpoint">还会清理 {summary.checkpoint.record_count} 条已精确归属的旧运行状态。</p>
              ) : null}
            </section>

            <section className="harness-cutover-retained" aria-labelledby="cutover-retained-title">
              <h2 id="cutover-retained-title">会保留</h2>
              <ul>
                <li>当前本地学习者身份和显示名称</li>
                <li>提醒时段与通知偏好</li>
                <li>此设备中的其他无关界面设置</li>
              </ul>
            </section>

            <section className="harness-cutover-confirmation" aria-label="确认切换">
              <label className="harness-cutover-confirm-checkbox">
                <input type="checkbox" checked={confirmed} disabled={pending} onChange={(event) => setConfirmed(event.target.checked)} />
                <span>我知道确认后旧学习记录不会因回退代码而恢复。</span>
              </label>
              <div className="harness-cutover-actions">
                <button className="harness-cutover-secondary" type="button" disabled={pending} onClick={() => void onRefresh()}>
                  刷新摘要
                </button>
                <button className="harness-cutover-primary" type="button" disabled={!confirmed || pending} onClick={() => void handleConfirm()}>
                  {pending || actionState === "loading" ? "正在核对并清理……" : "确认清理并进入 Tutor"}
                </button>
              </div>
            </section>
          </>
        ) : (
          <section className="harness-cutover-blocked" role="status" aria-live="polite">
            <h2>正在读取切换状态</h2>
            <p>请重新检查服务器给出的清理摘要。</p>
            <button className="harness-cutover-secondary" type="button" disabled={pending} onClick={() => void onRefresh()}>
              重新检查
            </button>
          </section>
        )}

        {actionMessage && (
          <p className={actionState === "error" ? "harness-cutover-feedback error" : "harness-cutover-feedback"} role={actionState === "error" ? "alert" : "status"}>
            {actionMessage}
          </p>
        )}
      </section>
    </main>
  );
}

function blockedTitle(code: string | undefined): string {
  if (code === "CUTOVER_TARGET_STATE_PRESENT") return "检测到尚未确认的 Tutor 数据";
  if (code === "CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED") return "无法安全确认旧运行状态的归属";
  return "当前无法完成受控切换";
}

function blockedMessage(code: string | undefined): string {
  if (code === "CUTOVER_TARGET_STATE_PRESENT") {
    return "系统发现了预切换的 Tutor 记录。为避免误删目标数据，本次切换已停止。";
  }
  if (code === "CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED") {
    return "系统无法把历史运行状态精确归属到当前学习者，因此不会执行宽泛清理。";
  }
  return "系统没有执行任何清理操作。";
}
