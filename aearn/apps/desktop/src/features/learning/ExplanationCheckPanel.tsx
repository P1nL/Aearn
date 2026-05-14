import type { ExplanationCheckResponse } from "../../types";
import { nextActionLabel } from "../../lib/desktopLabels";

export function ExplanationCheckPanel({ result }: { result: ExplanationCheckResponse }) {
  return (
    <article className="result-card explanation-check-card">
      <div className="panel-head">
        <h3>解释检查</h3>
        <span>{result.result}</span>
      </div>
      <p>{result.feedback}</p>
      <div className="metric-grid compact-metric-grid">
        <div>
          <span>得分</span>
          <strong>{result.score} / 2</strong>
        </div>
        <div>
          <span>后续动作</span>
          <strong>{nextActionLabel(result.next_action)}</strong>
        </div>
        <div>
          <span>需要追问</span>
          <strong>{result.follow_up_required ? "是" : "否"}</strong>
        </div>
      </div>
    </article>
  );
}
