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
};

export function SidebarNav({
  activeRoute,
  createdPlan,
  activeKnowledgePointId,
  openGroups,
  onToggleGroup,
  onRouteChange,
}: SidebarNavProps) {
  const learnItems = buildLearnNavItems(createdPlan, activeKnowledgePointId);
  const noteItems =
    createdPlan?.knowledge_points.slice(0, 5).map((knowledgePoint, index) => ({
      id: knowledgePoint.id,
      title: knowledgePoint.title,
      active: knowledgePoint.id === activeKnowledgePointId || (index === 0 && activeRoute === "notes"),
    })) ?? [
      { id: "note-js-1", title: "当前知识点笔记", active: activeRoute === "notes" },
      { id: "note-js-2", title: "错因与修正方式", active: false },
    ];

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
            {learnItems.map((item) => (
              <button
                className={activeRoute === "home" && item.active ? "nav-link active" : "nav-link"}
                key={item.id}
                type="button"
                onClick={() => onRouteChange("home")}
              >
                <span className="nav-dot"></span>
                <span>{item.title}</span>
              </button>
            ))}
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
            {["今日错因复习", "薄弱代码点"].map((item) => (
              <button
                className={activeRoute === "review" && item === "今日错因复习" ? "nav-link active" : "nav-link"}
                key={item}
                type="button"
                onClick={() => onRouteChange("review")}
              >
                <span className="nav-dot"></span>
                <span>{item}</span>
              </button>
            ))}
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
            {noteItems.map((item) => (
              <button
                className={activeRoute === "notes" && item.active ? "nav-link active" : "nav-link"}
                key={item.id}
                type="button"
                onClick={() => onRouteChange("notes")}
              >
                <span className="nav-dot"></span>
                <span>{item.title}</span>
              </button>
            ))}
          </div>
        </div>
      </section>
    </nav>
  );
}
