import type { AppRoute, NavGroupKey } from "../appTypes";
import type { CreatedPlanResponse } from "../types";
import { buildLearnNavItems } from "../lib/learningHelpers";

type SidebarNavProps = {
  activeRoute: AppRoute;
  createdPlan: CreatedPlanResponse | null;
  activeKnowledgePointId: string;
  openGroups: Record<NavGroupKey, boolean>;
  onToggleGroup: (group: NavGroupKey) => void;
  onRouteChange: (route: AppRoute) => void;
  onSelectKnowledgePoint: (knowledgePointId: string) => void;
};

export function SidebarNav({
  activeRoute,
  createdPlan,
  activeKnowledgePointId,
  openGroups,
  onToggleGroup,
  onRouteChange,
  onSelectKnowledgePoint,
}: SidebarNavProps) {
  const learnItems = buildLearnNavItems(createdPlan, activeKnowledgePointId);
  const reviewItems =
    createdPlan?.knowledge_points
      .filter((knowledgePoint) => knowledgePoint.status === "reviewing" || knowledgePoint.status === "mastered")
      .slice(0, 4)
      .map((knowledgePoint) => ({
        id: knowledgePoint.id,
        title: knowledgePoint.title,
        active: activeRoute === "review" && knowledgePoint.id === activeKnowledgePointId,
      })) ?? [];
  const noteItems =
    createdPlan?.knowledge_points.slice(0, 5).map((knowledgePoint, index) => ({
      id: knowledgePoint.id,
      title: knowledgePoint.title,
      active: knowledgePoint.id === activeKnowledgePointId || (index === 0 && activeRoute === "notes"),
    })) ?? [];

  return (
    <nav className="nav" aria-label="主导航">
      <section className={openGroups.learn ? "nav-group open" : "nav-group"} data-group="learn">
        <button
          className={activeRoute === "home" ? "nav-trigger nav-link active" : "nav-trigger nav-link"}
          type="button"
          aria-expanded={openGroups.learn}
          onClick={() => {
            onToggleGroup("learn");
            onRouteChange("home");
          }}
        >
          <span className="nav-dot"></span>
          <span>学习</span>
          <span className="nav-chevron">›</span>
        </button>
        <div className="submenu">
          <div className="submenu-inner">
            {learnItems.length > 0 ? (
              learnItems.map((item) => (
                <button
                  className={activeRoute === "home" && item.active ? "nav-link active" : "nav-link"}
                  key={item.id}
                  type="button"
                  onClick={() => onSelectKnowledgePoint(item.id)}
                >
                  <span className="nav-dot"></span>
                  <span>{item.title}</span>
                </button>
              ))
            ) : (
              <div className="nav-empty">完成建档后，这里只显示你的学习路线。</div>
            )}
          </div>
        </div>
      </section>

      <section className={openGroups.review ? "nav-group open" : "nav-group"} data-group="review">
        <button
          className={activeRoute === "review" ? "nav-trigger nav-link active" : "nav-trigger nav-link"}
          type="button"
          aria-expanded={openGroups.review}
          onClick={() => {
            onToggleGroup("review");
            onRouteChange("review");
          }}
        >
          <span className="nav-dot"></span>
          <span>复习</span>
          <span className="nav-chevron">›</span>
        </button>
        <div className="submenu">
          <div className="submenu-inner">
            {reviewItems.length > 0 ? (
              reviewItems.map((item) => (
                <button
                  className={item.active ? "nav-link active" : "nav-link"}
                  key={item.id}
                  type="button"
                  onClick={() => onRouteChange("review")}
                >
                  <span className="nav-dot"></span>
                  <span>{item.title}</span>
                </button>
              ))
            ) : (
              <div className="nav-empty">暂无到期复习知识点。</div>
            )}
          </div>
        </div>
      </section>

      <section className={openGroups.notes ? "nav-group open" : "nav-group"} data-group="notes">
        <button
          className={activeRoute === "notes" ? "nav-trigger nav-link active" : "nav-trigger nav-link"}
          type="button"
          aria-expanded={openGroups.notes}
          onClick={() => {
            onToggleGroup("notes");
            onRouteChange("notes");
          }}
        >
          <span className="nav-dot"></span>
          <span>笔记</span>
          <span className="nav-chevron">›</span>
        </button>
        <div className="submenu">
          <div className="submenu-inner">
            {noteItems.length > 0 ? (
              noteItems.map((item) => (
                <button
                  className={activeRoute === "notes" && item.active ? "nav-link active" : "nav-link"}
                  key={item.id}
                  type="button"
                  onClick={() => onRouteChange("notes")}
                >
                  <span className="nav-dot"></span>
                  <span>{item.title}</span>
                </button>
              ))
            ) : (
              <div className="nav-empty">学习路线生成后自动出现知识点笔记。</div>
            )}
          </div>
        </div>
      </section>
    </nav>
  );
}
