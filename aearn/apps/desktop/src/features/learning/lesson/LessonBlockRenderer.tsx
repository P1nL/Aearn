import type { ReactNode } from "react";

import type { LessonBlock, LessonExerciseGateBlock } from "../../../types";

type LessonBlockRendererProps = {
  block: LessonBlock;
  onCitation: (citationId: string) => void;
  renderExerciseGate?: (block: LessonExerciseGateBlock) => ReactNode;
};

export function LessonBlockRenderer({ block, onCitation, renderExerciseGate }: LessonBlockRendererProps) {
  const citations = <CitationMarkers citationIds={block.citation_ids} onCitation={onCitation} />;
  switch (block.type) {
    case "heading":
      return <header className="lesson-block lesson-heading"><p className="tutor-panel-eyebrow">结构化课程</p><h1>{block.title}</h1>{block.subtitle && <p>{block.subtitle}</p>}{citations}</header>;
    case "learning_objectives":
      return <section className="lesson-block lesson-objectives"><BlockTitle title="完成本课后，你将能够" /><ul>{block.items.map((item) => <li key={item}>{item}</li>)}</ul>{citations}</section>;
    case "concept":
      return <section className="lesson-block lesson-concept"><BlockTitle title={block.title} />{block.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}{citations}</section>;
    case "authority_note":
      return <aside className="lesson-block lesson-authority"><span aria-hidden="true">§</span><div><BlockTitle title={block.title} /><p>{block.statement}</p>{citations}</div></aside>;
    case "code_example":
      return <section className="lesson-block lesson-code"><BlockTitle title={block.title} /><pre><code>{block.code}</code></pre><div className="lesson-code-notice">静态教学示例 · 未在本任务中运行或验证</div>{block.explanation.map((item) => <p key={item}>{item}</p>)}{citations}</section>;
    case "comparison":
      return <section className="lesson-block lesson-comparison"><BlockTitle title={block.title} /><div className="lesson-table-wrap"><table><thead><tr>{block.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{block.rows.map((row, index) => <tr key={`${block.block_id}-${index}`}>{row.map((cell, cellIndex) => <td key={`${block.block_id}-${index}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div><p>{block.conclusion}</p>{citations}</section>;
    case "hint":
      return <aside className="lesson-block lesson-hint"><BlockTitle title={block.title} /><ol>{block.steps.map((step) => <li key={step}>{step}</li>)}</ol>{citations}</aside>;
    case "exercise_gate":
      return renderExerciseGate ? renderExerciseGate(block) : <section className="lesson-block lesson-gate"><div><p className="tutor-panel-eyebrow">练习 Gate slot</p><BlockTitle title="理解检查已冻结" /><p>{block.learner_prompt}</p></div><dl><div><dt>类型</dt><dd>{gateKindLabel(block.gate_kind)}</dd></div><div><dt>Contract</dt><dd>{block.assessment_contract_version}</dd></div><div><dt>能力</dt><dd>{block.required_capabilities.join("、")}</dd></div></dl><p className="lesson-gate-boundary">当前页面尚未连接 Gate capability seam。</p>{citations}</section>;
    case "summary":
      return <section className="lesson-block lesson-summary"><BlockTitle title="本课小结" /><ul>{block.points.map((point) => <li key={point}>{point}</li>)}</ul>{citations}</section>;
    case "next_steps":
      return <section className="lesson-block lesson-next"><BlockTitle title="接下来" /><ul>{block.items.map((item) => <li key={item}>{item}</li>)}</ul>{citations}</section>;
    default: {
      const unreachable: never = block;
      return <div role="alert">未知课程块：{String(unreachable)}</div>;
    }
  }
}

function BlockTitle({ title }: { title: string }) {
  return <h2>{title}</h2>;
}

function CitationMarkers({ citationIds, onCitation }: { citationIds: string[]; onCitation: (citationId: string) => void }) {
  if (citationIds.length === 0) return null;
  return <div className="lesson-citations" aria-label="本段引用来源">{citationIds.map((citationId, index) => <button key={citationId} type="button" onClick={() => onCitation(citationId)} aria-label={`查看引用来源 ${index + 1}`}>[{index + 1}]</button>)}</div>;
}

function gateKindLabel(kind: "knowledge_check" | "guided_practice" | "independent_practice"): string {
  return { knowledge_check: "知识检查", guided_practice: "引导练习", independent_practice: "独立练习" }[kind];
}
