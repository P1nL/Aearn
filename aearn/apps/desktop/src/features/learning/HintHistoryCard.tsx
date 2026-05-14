import type { HintResponse } from "../../types";

export function HintHistoryCard({ items }: { items: HintResponse[] }) {
  return (
    <article className="result-card hint-history-card">
      <div className="panel-head">
        <h3>提示历史</h3>
        <span>{items[0]?.hint_usage_count ?? 0} 次</span>
      </div>
      <ul className="hint-history-list">
        {items.map((item, index) => (
          <li key={`${item.hint.hint_level}-${index}`}>
            <strong>{item.hint.hint_level}</strong>
            <p>{item.hint.content}</p>
          </li>
        ))}
      </ul>
    </article>
  );
}
