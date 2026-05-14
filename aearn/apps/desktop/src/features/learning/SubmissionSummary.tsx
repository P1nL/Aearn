import type { SubmitExerciseResponse } from "../../types";

export function SubmissionSummary({ result }: { result: SubmitExerciseResponse }) {
  return (
    <article className="submit-summary">
      <div className="panel-head">
        <div>
          <div className="kicker">Submit Result</div>
          <h3>提交摘要</h3>
        </div>
        <span className="result-pill">{result.code_completion_result.result}</span>
      </div>

      <p>{result.code_completion_result.feedback}</p>

      <div className="metric-grid">
        <div>
          <span>总分</span>
          <strong>{result.code_completion_result.score} / 8</strong>
        </div>
        <div>
          <span>FSRS Rating</span>
          <strong>{result.code_completion_result.fsrs_rating}</strong>
        </div>
        <div>
          <span>下一步</span>
          <strong>{result.next_action}</strong>
        </div>
      </div>

      <div className="gate-grid">
        {Object.entries(result.code_completion_result.hard_gates).map(([gate, passed]) => (
          <div className={passed ? "gate-pass" : "gate-fail"} key={gate}>
            <span>{gate}</span>
            <strong>{passed ? "pass" : "fail"}</strong>
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
