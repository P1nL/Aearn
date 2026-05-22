import type { SubmitExerciseResponse } from "../../types";

export function SubmissionSummary({ result }: { result: SubmitExerciseResponse }) {
  return (
    <article className="submit-summary">
      <div className="panel-head">
        <div>
          <div className="kicker">提交结果</div>
          <h3>提交摘要</h3>
        </div>
        <span className="result-pill">{resultLabel(result.code_completion_result.result)}</span>
      </div>

      <p>{result.code_completion_result.feedback}</p>

      <div className="metric-grid">
        <div>
          <span>总分</span>
          <strong>{result.code_completion_result.score} / 8</strong>
        </div>
        <div>
          <span>掌握程度</span>
          <strong>{fsrsRatingLabel(result.code_completion_result.fsrs_rating)}</strong>
        </div>
        <div>
          <span>建议</span>
          <strong>{nextActionLabel(result.next_action)}</strong>
        </div>
      </div>

      <div className="gate-grid">
        {Object.entries(result.code_completion_result.hard_gates).map(([gate, passed]) => (
          <div className={passed ? "gate-pass" : "gate-fail"} key={gate}>
            <span>{gateLabel(gate)}</span>
            <strong>{passed ? "通过" : "未通过"}</strong>
          </div>
        ))}
      </div>

      {result.code_completion_result.weak_points.length > 0 && (
        <ul className="weak-point-list">
          {result.code_completion_result.weak_points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      )}
    </article>
  );
}

function resultLabel(value: string): string {
  if (value === "pass") {
    return "通过";
  }
  if (value === "fail") {
    return "未通过";
  }
  return value;
}

function fsrsRatingLabel(rating: string | number): string {
  if (rating === "again" || rating === 1) {
    return "需要重学";
  }
  if (rating === "hard" || rating === 2) {
    return "较困难";
  }
  if (rating === "good" || rating === 3) {
    return "良好";
  }
  if (rating === "easy" || rating === 4) {
    return "轻松掌握";
  }
  return String(rating);
}

function nextActionLabel(action: string): string {
  if (action === "show_hint") {
    return "获取提示";
  }
  if (action === "explain_error") {
    return "解释错误";
  }
  if (action === "review_variant") {
    return "复习变体";
  }
  if (action === "schedule_review") {
    return "安排复习";
  }
  if (action === "advance_next") {
    return "继续下一步";
  }
  return "重新运行";
}

function gateLabel(gate: string): string {
  if (gate === "tests_pass") {
    return "测试通过";
  }
  if (gate === "explanation_ok") {
    return "解释合格";
  }
  if (gate === "no_runtime_error") {
    return "无运行错误";
  }
  if (gate === "blanks_filled") {
    return "空缺已填";
  }
  return gate;
}
