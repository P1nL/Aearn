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
              <h3 className="trace-title">分析学习目标</h3>
              <p className="trace-body">识别用户目标：JavaScript/HTML/CSS、Python、AI 生成代码理解、测试验证。</p>
            </div>
          </article>
          <article className="trace-card">
            <span className="trace-dot"></span>
            <div>
              <h3 className="trace-title">澄清细节</h3>
              <p className="trace-body">继续追问当前水平、目标用途、运行环境和时间边界。</p>
            </div>
          </article>
          <article className="trace-card">
            <span className="trace-dot"></span>
            <div>
              <h3 className="trace-title">生成课程草稿</h3>
              <p className="trace-body">根据语言目标生成五段编程课程草稿。</p>
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
        {routeCards.map((card) => (
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
        ))}
      </div>
    </section>
  );
}
