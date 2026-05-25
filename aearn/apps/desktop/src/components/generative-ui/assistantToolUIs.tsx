import { makeAssistantToolUI, type ToolCallMessagePartProps } from "@assistant-ui/react";

import { LearningRouteCard } from "./LearningRouteCard";
import type { LearningRouteArgs, ToolUIProps } from "./types";

type ToolStatus = ToolUIProps<unknown>["status"];

function mapStatusToToolStatus(status: ToolCallMessagePartProps<unknown>["status"]): ToolStatus {
  switch (status.type) {
    case "running":
      return "running";
    case "complete":
      return "done";
    case "incomplete":
      return "error";
    case "requires-action":
      return "running";
    default:
      return "pending";
  }
}

const EMPTY_LEARNING_ROUTE: LearningRouteArgs = {
  plan_id: "",
  goal_text: "正在生成学习路线…",
  language: "javascript",
  modules: [],
};

function isPartialLearningRouteArgs(value: unknown): value is Partial<LearningRouteArgs> {
  return typeof value === "object" && value !== null;
}

function normalizeLearningRouteArgs(args: unknown): LearningRouteArgs {
  if (!isPartialLearningRouteArgs(args)) {
    return EMPTY_LEARNING_ROUTE;
  }
  return {
    plan_id: typeof args.plan_id === "string" ? args.plan_id : EMPTY_LEARNING_ROUTE.plan_id,
    goal_text: typeof args.goal_text === "string" ? args.goal_text : EMPTY_LEARNING_ROUTE.goal_text,
    language: (args.language as LearningRouteArgs["language"]) ?? EMPTY_LEARNING_ROUTE.language,
    modules: Array.isArray(args.modules)
      ? args.modules
          .filter((module): module is Record<string, unknown> & LearningRouteArgs["modules"][number] =>
            typeof module === "object" && module !== null,
          )
          .map((module, index) => {
            const knowledgePointsRaw = (module as Record<string, unknown>).knowledge_points;
            return {
              id: typeof module.id === "string" ? module.id : `module_${index}`,
              title: typeof module.title === "string" ? module.title : "未命名模块",
              order_index: typeof module.order_index === "number" ? module.order_index : index,
              status:
                module.status === "completed" ||
                module.status === "in_progress" ||
                module.status === "skipped" ||
                module.status === "pending"
                  ? module.status
                  : "pending",
              estimated_sessions:
                typeof module.estimated_sessions === "number" ? module.estimated_sessions : 1,
              knowledge_points: Array.isArray(knowledgePointsRaw)
                ? knowledgePointsRaw
                    .filter(
                      (kp): kp is Record<string, unknown> & LearningRouteArgs["modules"][number]["knowledge_points"][number] =>
                        typeof kp === "object" && kp !== null,
                    )
                    .map((kp, kpIndex) => ({
                      id: typeof kp.id === "string" ? kp.id : `kp_${index}_${kpIndex}`,
                      title: typeof kp.title === "string" ? kp.title : "未命名知识点",
                      status:
                        kp.status === "mastered" ||
                        kp.status === "learning" ||
                        kp.status === "reviewing" ||
                        kp.status === "pending"
                          ? kp.status
                          : "pending",
                      mastery_score:
                        typeof kp.mastery_score === "number" ? kp.mastery_score : 0,
                    }))
                : [],
            };
          })
      : EMPTY_LEARNING_ROUTE.modules,
  };
}

export const LearningRouteToolUI = makeAssistantToolUI<LearningRouteArgs, unknown>({
  toolName: "show_learning_route",
  render: ({ args, status }) => {
    const normalized = normalizeLearningRouteArgs(args);
    const cardStatus = mapStatusToToolStatus(status);
    return <LearningRouteCard args={normalized} status={cardStatus} />;
  },
});
