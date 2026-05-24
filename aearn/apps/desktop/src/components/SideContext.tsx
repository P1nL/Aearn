import type { AppRoute } from "../appTypes";
import type { CreatedPlanResponse, SubmitExerciseResponse } from "../types";
import { buildReviewCards, buildRouteCards } from "../lib/learningHelpers";

type SideContextProps = {
  route: AppRoute;
  createdPlan: CreatedPlanResponse | null;
  activeKnowledgePointId: string;
  lastSubmit: SubmitExerciseResponse | null;
  onSelectKnowledgePoint: (knowledgePointId: string) => void;
};

export function SideContext({
  route,
  createdPlan,
  activeKnowledgePointId,
  lastSubmit,
  onSelectKnowledgePoint,
}: SideContextProps) {
  if (route === "settings") {
    return null;
  }

  if (route === "onboarding") {
    return (
      <section className="side-context" aria-live="polite">
        <h2>建档进度</h2>
        <div className="context-stack">
          <article className="trace-card">
            <span className="trace-dot"></span>
            <div>
              <h3 className="trace-title">等待学习目标</h3>
              <p className="trace-body">输入你要掌握的语言、目标任务和时间边界后，路线才会生成。</p>
            </div>
          </article>
          <article className="trace-card">
            <span className="trace-dot"></span>
            <div>
              <h3 className="trace-title">生成学习路线</h3>
              <p className="trace-body">左侧栏会改为真实模块和知识点，不再展示固定示例标题。</p>
            </div>
          </article>
          <article className="trace-card">
            <span className="trace-dot"></span>
            <div>
              <h3 className="trace-title">进入对话练习</h3>
              <p className="trace-body">选择一个知识点后，主区加载真实会话、练习卡片和 Agent 对话。</p>
            </div>
          </article>
        </div>
      </section>
    );
  }

  if (route === "review") {
    const reviewCards = buildReviewCards(lastSubmit);
    return (
      <section className="side-context" aria-live="polite">
        <h2>复习概览</h2>
        <div className="context-stack">
          {reviewCards.map((card, index) => (
            <article className={index === 0 ? "review-mini active" : "review-mini"} key={card.title}>
              <h3 className="mini-title">{card.title}</h3>
              <p className="mini-body">{card.body}</p>
            </article>
          ))}
        </div>
      </section>
    );
  }

  const routeCards = buildRouteCards(createdPlan, activeKnowledgePointId);
  return (
    <section className="side-context" aria-live="polite">
      <h2>编程路线</h2>
      <div className="context-stack">
        {routeCards.length > 0 ? (
          routeCards.map((card) => (
            <button
              className={card.active ? "route-card route-card-button active" : "route-card route-card-button"}
              key={card.id}
              type="button"
              disabled={!card.knowledgePointId}
              onClick={() => {
                if (card.knowledgePointId) {
                  onSelectKnowledgePoint(card.knowledgePointId);
                }
              }}
            >
              <span className="route-index">{card.index}</span>
              <div>
                <h3 className="mini-title">{card.title}</h3>
                <p className="mini-body">{card.body}</p>
              </div>
            </button>
          ))
        ) : (
          <article className="route-card empty">
            <span className="route-index">0</span>
            <div>
              <h3 className="mini-title">尚未生成路线</h3>
              <p className="mini-body">完成建档后，这里会显示用户学习内容生成的模块。</p>
            </div>
          </article>
        )}
      </div>
    </section>
  );
}
