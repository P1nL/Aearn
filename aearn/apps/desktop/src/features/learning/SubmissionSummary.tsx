import type { SubmitExerciseResponse } from "../../types";
import { completionResultLabel, fsrsRatingLabel, hardGateLabel, nextActionLabel } from "../../lib/desktopLabels";

export function SubmissionSummary({ result }: { result: SubmitExerciseResponse }) {
  return (
    <article className="submit-summary">
      <div className="panel-head">
        <div>
          <div className="kicker">提交结果</div>
          <h3>提交摘要</h3>
        </div>
        <span className="result-pill">{completionResultLabel(result.code_completion_result.result)}</span>
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
            <span>{hardGateLabel(gate)}</span>
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
