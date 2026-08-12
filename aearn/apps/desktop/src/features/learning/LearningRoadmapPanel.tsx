import type { LearningRoadmap, LearningRoadmapNode, ReviewQueue } from "../../types";

type LearningRoadmapPanelProps = {
  roadmap: LearningRoadmap;
  reviewQueue: ReviewQueue;
  selectedKnowledgeKey: string | null;
  mode: "lesson" | "review";
  onSelectLesson: (knowledgeKey: string) => void;
  onOpenReview: (knowledgeKey?: string) => void;
};

export function LearningRoadmapPanel({
  roadmap,
  reviewQueue,
  selectedKnowledgeKey,
  mode,
  onSelectLesson,
  onOpenReview,
}: LearningRoadmapPanelProps) {
  return (
    <nav className="learning-roadmap-panel" aria-label="学习路线">
      <header className="learning-roadmap-heading">
        <p className="tutor-panel-eyebrow">服务端路线</p>
        <h2>{roadmap.title}</h2>
        <span>{roadmap.target_level} · {roadmap.modules.length} 个模块</span>
      </header>

      <button
        className={`learning-review-entry${mode === "review" ? " active" : ""}`}
        type="button"
        disabled={reviewQueue.due_count === 0}
        onClick={() => onOpenReview(reviewQueue.critical_prerequisite_gate?.knowledge_key)}
      >
        <span aria-hidden="true">↺</span>
        <span><strong>今日复习</strong><small>{reviewQueue.due_count > 0 ? `${reviewQueue.due_count} 个知识点到期` : "当前没有到期复习"}</small></span>
        {reviewQueue.critical_prerequisite_gate ? <em>关键</em> : null}
      </button>

      <div className="learning-roadmap-modules">
        {roadmap.modules.map((module, moduleIndex) => (
          <section className="learning-roadmap-module" key={module.module_id} aria-labelledby={`roadmap-module-${module.module_id}`}>
            <header>
              <span>{String(moduleIndex + 1).padStart(2, "0")}</span>
              <div><strong id={`roadmap-module-${module.module_id}`}>{module.title}</strong><small>{module.description}</small></div>
            </header>
            <ol>
              {module.nodes.map((node) => (
                <li key={node.node_id}>
                  <RoadmapNodeButton
                    node={node}
                    selected={mode === "lesson" && node.knowledge_key === selectedKnowledgeKey}
                    onSelect={() => onSelectLesson(node.knowledge_key)}
                  />
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
    </nav>
  );
}

function RoadmapNodeButton({ node, selected, onSelect }: { node: LearningRoadmapNode; selected: boolean; onSelect: () => void }) {
  const locked = node.progress_status === "locked";
  return (
    <button
      className={`learning-roadmap-node ${node.progress_status}${selected ? " selected" : ""}`}
      type="button"
      disabled={locked}
      aria-current={selected ? "step" : undefined}
      onClick={onSelect}
    >
      <span className="learning-roadmap-node-mark" aria-hidden="true">{statusMark(node.progress_status)}</span>
      <span className="learning-roadmap-node-copy">
        <strong>{node.title}</strong>
        <small>{node.description}</small>
        <em>{statusLabel(node.progress_status)} · 掌握置信度 {Math.round(node.mastery_confidence * 100)}%</em>
      </span>
    </button>
  );
}

function statusMark(status: LearningRoadmapNode["progress_status"]): string {
  if (status === "completed" || status === "diagnostic_skipped") return "✓";
  if (status === "in_progress") return "→";
  if (status === "review_due") return "↺";
  if (status === "locked") return "·";
  return "○";
}

function statusLabel(status: LearningRoadmapNode["progress_status"]): string {
  return {
    locked: "未解锁",
    available: "可开始",
    in_progress: "学习中",
    completed: "已完成",
    review_due: "待复习",
    diagnostic_skipped: "诊断跳过",
  }[status];
}
