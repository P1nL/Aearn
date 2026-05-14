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
            <NestedNotesGroup
              groupKey="notes-python"
              title="Python"
              items={["DOM 事件补全", "Python 返回值", "测试断言"]}
              activeRoute={activeRoute}
              isOpen={openGroups["notes-python"]}
              onToggle={onToggleGroup}
              onRouteChange={onRouteChange}
            />
            <NestedNotesGroup
              groupKey="notes-javascript"
              title="JavaScript"
              items={["按钮点击计数", "输入框字数统计"]}
              activeRoute={activeRoute}
              isOpen={openGroups["notes-javascript"]}
              onToggle={onToggleGroup}
              onRouteChange={onRouteChange}
            />
            <NestedNotesGroup
              groupKey="notes-sql"
              title="SQL"
              items={["查询结果校验"]}
              activeRoute={activeRoute}
              isOpen={openGroups["notes-sql"]}
              onToggle={onToggleGroup}
              onRouteChange={onRouteChange}
            />
          </div>
        </div>
      </section>
    </nav>
  );
}

type NestedNotesGroupProps = {
  groupKey: NavGroupKey;
  title: string;
  items: string[];
  activeRoute: AppRoute;
  isOpen: boolean;
  onToggle: (group: NavGroupKey) => void;
  onRouteChange: (route: AppRoute) => void;
};

function NestedNotesGroup({
  groupKey,
  title,
  items,
  activeRoute,
  isOpen,
  onToggle,
  onRouteChange,
}: NestedNotesGroupProps) {
  return (
    <section className={isOpen ? "nav-group nested open" : "nav-group nested"} data-group={groupKey}>
      <button
        className={activeRoute === "notes" ? "nav-trigger nav-link active" : "nav-trigger nav-link"}
        type="button"
        aria-expanded={isOpen}
        onClick={() => {
          onToggle(groupKey);
          onRouteChange("notes");
        }}
      >
        <span className="nav-dot"></span>
        <span>{title}</span>
        <span className="nav-chevron">›</span>
      </button>
      <div className="submenu">
        <div className="submenu-inner">
          {items.map((item, index) => (
            <button
              className={activeRoute === "notes" && index === 0 ? "nav-link active" : "nav-link"}
              key={item}
              type="button"
              onClick={() => onRouteChange("notes")}
            >
              <span className="nav-dot"></span>
              <span>{item}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
