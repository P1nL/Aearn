import type { ExerciseRunMode } from "../../appTypes";
import type { RunExerciseResponse } from "../../types";
import { nextActionLabel, runtimeStatusLabel } from "../../lib/desktopLabels";

type RuntimeFeedbackProps = {
  result: RunExerciseResponse;
  runMode: ExerciseRunMode | null;
};

export function RuntimeFeedback({ result, runMode }: RuntimeFeedbackProps) {
  return (
    <div className="runtime-feedback-grid">
      {result.preview_html && (
        <article className="result-card">
          <div className="panel-head">
            <h3>浏览器预览</h3>
            <span>{runMode === "preview" ? "preview" : `${Math.round(result.test_pass_rate * 100)}%`}</span>
          </div>
          <iframe className="preview-frame" srcDoc={result.preview_html} title="exercise-preview" />
        </article>
      )}

      <article className="result-card">
        <div className="panel-head">
          <h3>{runMode === "preview" ? "运行反馈" : "测试与运行反馈"}</h3>
          <span>{runtimeStatusLabel(result.runtime_status)}</span>
        </div>
        <p className="meta">
          通过 {result.passed_test_count} / {result.total_test_count} · 下一步 {nextActionLabel(result.next_action)}
        </p>
        {result.stdout && (
          <div className="output-block">
            <strong>stdout</strong>
            <pre>{result.stdout}</pre>
          </div>
        )}
        {result.stderr && (
          <div className="output-block">
            <strong>stderr</strong>
            <pre>{result.stderr}</pre>
          </div>
        )}
        {result.error_message && <p className="mini-body">{result.error_message}</p>}
        <ul className="test-result-list">
          {result.test_results.map((item) => (
            <li className={item.passed ? "passed" : "failed"} key={item.case_id}>
              <strong>{item.case_type}</strong>
              <span>{item.message}</span>
            </li>
          ))}
        </ul>
      </article>
    </div>
  );
}
