import type { LessonCitation } from "../../../types";

type LessonSourcesPanelProps = {
  sources: LessonCitation[];
  selectedCitationId: string | null;
  onSelect: (citationId: string) => void;
};

export function LessonSourcesPanel({ sources, selectedCitationId, onSelect }: LessonSourcesPanelProps) {
  return (
    <aside className="lesson-sources" aria-labelledby="lesson-sources-title">
      <header><p className="tutor-panel-eyebrow">Evidence</p><h2 id="lesson-sources-title">权威来源</h2><span>{sources.length} 条冻结快照</span></header>
      <div className="lesson-source-list">
        {sources.map((source, index) => {
          const selected = source.citation_id === selectedCitationId;
          return (
            <article id={`source-${source.citation_id}`} key={source.citation_id} className={selected ? "lesson-source selected" : "lesson-source"}>
              <button type="button" className="lesson-source-heading" onClick={() => onSelect(source.citation_id)} aria-expanded={selected}>
                <span>{index + 1}</span><span><strong>{source.display_name}</strong><small>{source.provider}</small></span>
              </button>
              {selected && <div className="lesson-source-detail"><div className="lesson-source-badges"><span>{trustLabel(source.trust_tier)}</span><span>{source.source_version_label}</span><span>{source.source_version_kind === "fixed" ? "固定版本" : "滚动版本"}</span></div><p>{source.section_path.join(" / ") || "文档首页"}</p><blockquote>{source.evidence_excerpt}</blockquote><dl><div><dt>抓取</dt><dd>{formatTime(source.fetched_at)}</dd></div><div><dt>冻结</dt><dd>{formatTime(source.snapshotted_at)}</dd></div></dl><a href={source.canonical_url} target="_blank" rel="noreferrer">打开原始文档</a></div>}
            </article>
          );
        })}
      </div>
    </aside>
  );
}

function trustLabel(value: LessonCitation["trust_tier"]): string {
  return { official: "官方来源", trusted_de_facto: "受信事实来源", internal: "内部受信来源" }[value];
}
function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { year: "numeric", month: "short", day: "numeric" });
}
