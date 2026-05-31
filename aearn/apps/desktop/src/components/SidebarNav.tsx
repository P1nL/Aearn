import { useState } from "react";

import type { AppRoute, NavGroupKey } from "../appTypes";
import type { CreatedPlanResponse } from "../types";
import { buildLearnNavItems } from "../lib/learningHelpers";

const NAV_PREVIEW_LIMIT = 5;

type LimitedNavGroupKey = "learn" | "review" | "notes";

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
  const [expandedSubmenus, setExpandedSubmenus] = useState<Record<LimitedNavGroupKey, boolean>>({
    learn: false,
    review: false,
    notes: false,
  });
  const learnItems = buildLearnNavItems(createdPlan, activeKnowledgePointId);
  const reviewItems =
    createdPlan?.knowledge_points
      .filter((knowledgePoint) => knowledgePoint.status === "reviewing" || knowledgePoint.status === "mastered")
      .map((knowledgePoint) => ({
        id: knowledgePoint.id,
        title: knowledgePoint.title,
        active: activeRoute === "review" && knowledgePoint.id === activeKnowledgePointId,
      })) ?? [];
  const noteItems =
    createdPlan?.knowledge_points.map((knowledgePoint, index) => ({
      id: knowledgePoint.id,
      title: knowledgePoint.title,
      active: knowledgePoint.id === activeKnowledgePointId || (index === 0 && activeRoute === "notes"),
    })) ?? [];
  const visibleLearnItems = getPreviewItems(learnItems, expandedSubmenus.learn);
  const visibleReviewItems = getPreviewItems(reviewItems, expandedSubmenus.review);
  const visibleNoteItems = getPreviewItems(noteItems, expandedSubmenus.notes);

  function toggleSubmenuPreview(group: LimitedNavGroupKey) {
    setExpandedSubmenus((current) => ({
      ...current,
      [group]: !current[group],
    }));
  }

  return (
    <nav className="nav" aria-label="主导航">
      <section className={openGroups.learn ? "nav-group open" : "nav-group"} data-group="learn">
        <button
          className={activeRoute === "home" ? "nav-trigger nav-link active" : "nav-trigger nav-link"}
          type="button"
          aria-expanded={openGroups.learn}
          onClick={() => onToggleGroup("learn")}
        >
          <span className="nav-dot"></span>
          <span>学习</span>
          <span className="nav-chevron">›</span>
        </button>
        <div className="submenu">
          <div className="submenu-inner">
            {learnItems.length > 0 ? (
              visibleLearnItems.map((item) => (
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
            {learnItems.length > NAV_PREVIEW_LIMIT && (
              <button
                className="nav-more"
                type="button"
                aria-expanded={expandedSubmenus.learn}
                onClick={() => toggleSubmenuPreview("learn")}
              >
                {expandedSubmenus.learn ? "收起显示" : "展开显示"}
              </button>
            )}
          </div>
        </div>
      </section>

      <section className={openGroups.review ? "nav-group open" : "nav-group"} data-group="review">
        <button
          className={activeRoute === "review" ? "nav-trigger nav-link active" : "nav-trigger nav-link"}
          type="button"
          aria-expanded={openGroups.review}
          onClick={() => onToggleGroup("review")}
        >
          <span className="nav-dot"></span>
          <span>复习</span>
          <span className="nav-chevron">›</span>
        </button>
        <div className="submenu">
          <div className="submenu-inner">
            {reviewItems.length > 0 ? (
              visibleReviewItems.map((item) => (
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
            {reviewItems.length > NAV_PREVIEW_LIMIT && (
              <button
                className="nav-more"
                type="button"
                aria-expanded={expandedSubmenus.review}
                onClick={() => toggleSubmenuPreview("review")}
              >
                {expandedSubmenus.review ? "收起显示" : "展开显示"}
              </button>
            )}
          </div>
        </div>
      </section>

      <section className={openGroups.notes ? "nav-group open" : "nav-group"} data-group="notes">
        <button
          className={activeRoute === "notes" ? "nav-trigger nav-link active" : "nav-trigger nav-link"}
          type="button"
          aria-expanded={openGroups.notes}
          onClick={() => onToggleGroup("notes")}
        >
          <span className="nav-dot"></span>
          <span>笔记</span>
          <span className="nav-chevron">›</span>
        </button>
        <div className="submenu">
          <div className="submenu-inner">
            {noteItems.length > 0 ? (
              visibleNoteItems.map((item) => (
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
            {noteItems.length > NAV_PREVIEW_LIMIT && (
              <button
                className="nav-more"
                type="button"
                aria-expanded={expandedSubmenus.notes}
                onClick={() => toggleSubmenuPreview("notes")}
              >
                {expandedSubmenus.notes ? "收起显示" : "展开显示"}
              </button>
            )}
          </div>
        </div>
      </section>
    </nav>
  );
}

function getPreviewItems<T>(items: T[], expanded: boolean): T[] {
  if (expanded) {
    return items;
  }
  return items.slice(0, NAV_PREVIEW_LIMIT);
}
