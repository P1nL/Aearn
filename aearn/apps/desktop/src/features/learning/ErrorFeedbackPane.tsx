import type { ExplainErrorResponse } from "../../types";

export function ErrorFeedbackPane({ result }: { result: ExplainErrorResponse }) {
  return (
    <article className="result-card error-feedback-card">
      <div className="panel-head">
        <h3>错因解释</h3>
        <span>{result.error_cause}</span>
      </div>
      <p>{result.explanation}</p>
      <div className="output-block">
        <strong>修正建议</strong>
        <p>{result.fix_suggestion}</p>
      </div>
      {result.related_knowledge_points.length > 0 && (
        <div className="related-kp-strip">
          {result.related_knowledge_points.map((item) => (
            <span key={item.id}>{item.title}</span>
          ))}
        </div>
      )}
    </article>
  );
}
