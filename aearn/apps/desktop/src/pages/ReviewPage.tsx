import type { ConversationMessage } from "../appTypes";
import type { RunExerciseResponse, SubmitExerciseResponse } from "../types";
import { ReviewRecap } from "../components/ReviewRecap";
import { ThreadMessages } from "../components/ThreadMessages";

type ReviewPageProps = {
  messages: ConversationMessage[];
  lastSubmit: SubmitExerciseResponse | null;
  lastRun: RunExerciseResponse | null;
};

export function ReviewPage({ messages, lastSubmit, lastRun }: ReviewPageProps) {
  return (
    <div className="review-screen">
      <div className="review-thread-wrap">
        <section className="conversation" aria-label="复习新会话">
          <div className="thread">
            <div className="lesson-title">
              <p>这是一个独立新会话，避免和当前代码练习互相干扰。输入栏保持与主页一致。</p>
            </div>

            <ThreadMessages messages={messages} />

            {lastSubmit && (
              <article className="message agent">
                <div className="avatar">A</div>
                <div className="bubble">
                  <div className="bubble-label">Agent</div>
                  <p>最近一次提交已经写回复习状态。下一轮会优先追打 {lastSubmit.code_completion_result.weak_points[0] ?? "状态变量生命周期"}。</p>
                  <div className="tool-card">
                    FSRS：{lastSubmit.code_completion_result.fsrs_rating} · 下一步：{lastSubmit.next_action}
                  </div>
                </div>
              </article>
            )}

            <ReviewRecap lastSubmit={lastSubmit} lastRun={lastRun} />
          </div>
        </section>
      </div>
    </div>
  );
}
