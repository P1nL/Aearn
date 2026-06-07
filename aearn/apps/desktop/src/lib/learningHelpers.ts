import type {
  AsyncActionState,
  ConversationMessage,
  DraftModuleCard,
  ExerciseRunMode,
  LearnNavItem,
  ReviewCard,
  RouteCard,
} from "../appTypes";
import { ApiRequestError } from "../types";
import type {
  CreatedPlanResponse,
  LearningExercise,
  LearningSessionResponse,
  PlanDraft,
  RunExerciseResponse,
  SubmitExerciseResponse,
} from "../types";
import {
  completionResultLabel,
  fsrsRatingLabel,
  knowledgePointStatusLabel,
  nextActionLabel,
  runtimeLabel,
  runtimeStatusLabel,
} from "./desktopLabels";

let messageCounter = 0;

export function buildLearnNavItems(plan: CreatedPlanResponse | null, activeKnowledgePointId: string): LearnNavItem[] {
  if (!plan) {
    return [];
  }

  return plan.knowledge_points.map((knowledgePoint, index) => ({
    id: knowledgePoint.id,
    title: knowledgePoint.title,
    active: knowledgePoint.id === activeKnowledgePointId || (index === 0 && activeKnowledgePointId.length === 0),
  }));
}

export function buildRouteCards(plan: CreatedPlanResponse | null, activeKnowledgePointId: string): RouteCard[] {
  if (!plan) {
    return [];
  }

  return plan.modules.slice(0, 5).map((module, index) => {
    const firstKnowledgePoint = plan.knowledge_points.find((item) => item.module_id === module.id);
    const summary = firstKnowledgePoint ? `${knowledgePointStatusLabel(firstKnowledgePoint.status)} · ${firstKnowledgePoint.title}` : "未开始";
    return {
      id: module.id,
      index: index + 1,
      title: module.title,
      body: summary,
      active: firstKnowledgePoint?.id === activeKnowledgePointId,
      knowledgePointId: firstKnowledgePoint?.id ?? "",
    };
  });
}

export function buildReviewCards(
  lastSubmit: SubmitExerciseResponse | null,
  lastRun?: RunExerciseResponse | null,
): ReviewCard[] {
  if (!lastSubmit) {
    return [];
  }

  return [
    {
      title: lastSubmit.code_completion_result.weak_points[0] ?? "状态变量生命周期",
      body: `最新评分 ${lastSubmit.code_completion_result.score} / 8，掌握程度 ${fsrsRatingLabel(lastSubmit.code_completion_result.fsrs_rating)}。`,
    },
    {
      title: "运行结果",
      body: lastRun ? `可见测试通过 ${lastRun.passed_test_count}/${lastRun.total_test_count}。` : "本次提交未保留运行详情。",
    },
    {
      title: "下一步",
      body: `建议：${nextActionLabel(lastSubmit.next_action)}，知识点状态已更新为 ${knowledgePointStatusLabel(lastSubmit.KnowledgePoint.status)}。`,
    },
  ];
}

export function mapDraftModuleCard(module: PlanDraft["modules"][number]): DraftModuleCard {
  const tagBySource: Record<PlanDraft["modules"][number]["source"], { text: string; className: string }> = {
    template: { text: module.order_index === 2 ? "主干" : "保留", className: module.order_index === 2 ? "tag warn" : "tag strong" },
    user_material: { text: "新增", className: "tag" },
    agent_generated: { text: "可调", className: "tag" },
  };
  const tag = tagBySource[module.source];
  return {
    id: module.temp_id,
    title: module.title,
    description: module.description ?? "等待确认后写入正式学习计划",
    tag: tag.text,
    tagClass: tag.className,
  };
}

export function buildSessionNote(session: LearningSessionResponse, exercise: LearningExercise): string {
  return `# ${exercise.title}

知识点：${session.context_snapshot.KnowledgePoint.title}
运行能力：${runtimeLabel(exercise.runtime_profile.runtime_tier)}

题面：
${exercise.prompt_markdown}

练习记录：
- 先运行最小修改，再根据可见测试决定是否提交。
- 如果失败，记录错因、修改位置和下一步问题。`;
}

export function buildAttemptDraft(
  exercise: LearningExercise,
  lastRun: RunExerciseResponse | null,
  lastSubmit: SubmitExerciseResponse | null,
): string {
  const lines = [`${exercise.title}`];
  if (lastRun) {
    lines.push("", `运行结果：${runtimeStatusLabel(lastRun.runtime_status)}，通过 ${lastRun.passed_test_count}/${lastRun.total_test_count}。`);
    if (lastRun.error_message) {
      lines.push(`错误：${lastRun.error_message}`);
    }
  }
  if (lastSubmit) {
    lines.push("", `提交结果：${completionResultLabel(lastSubmit.code_completion_result.result)}，评分 ${lastSubmit.code_completion_result.score}/8。`);
    lines.push(`反馈：${lastSubmit.code_completion_result.feedback}`);
  }
  if (!lastRun && !lastSubmit) {
    lines.push("", "练习记录：先补全最小代码，再运行可见测试。");
  }
  return lines.join("\n");
}

export function buildRunAgentFeedback(result: RunExerciseResponse, runMode: ExerciseRunMode): string {
  const actionLabel = nextActionLabel(result.next_action);
  if (result.runtime_status === "unsupported") {
    return "当前语言的运行能力还没有开放，先按题面做静态理解和补全；如果需要继续练习，我会引导你换到当前支持的运行环境。";
  }

  if (result.runtime_status !== "success") {
    const errorSummary = result.error_message ? `\n\n错误摘要：${result.error_message}` : "";
    return `这次${runMode === "preview" ? "预览" : "可见测试"}没有通过，先看右侧真实运行结果。你可以点“解释这个错误”，我会按 stderr 和失败测试拆解原因。${errorSummary}`;
  }

  if (runMode === "preview") {
    return `预览已经运行成功。先确认输出是否符合题意；如果要进入评分，请再运行可见测试，然后提交结果。`;
  }

  if (result.total_test_count === 0) {
    return `代码运行成功。下一步建议：${actionLabel}。`;
  }

  if (result.passed_test_count === result.total_test_count) {
    return `可见测试全部通过：${result.passed_test_count}/${result.total_test_count}。当前结果可以提交；提交后我会根据评分结果安排下一步。`;
  }

  return `代码已经能运行，但可见测试只通过 ${result.passed_test_count}/${result.total_test_count}。先对照右侧失败项修正，也可以让我解释这个错误。`;
}

export function buildSubmitAgentFeedback(result: SubmitExerciseResponse): string {
  const feedback = result.code_completion_result.feedback.trim() || "提交已记录，评分结果已经写回当前知识点。";
  return `${feedback}\n\n本次得分 ${result.code_completion_result.score}/8，下一步建议：${nextActionLabel(result.next_action)}。`;
}

export function mergeAttemptIntoNote(currentNote: string, attempt: string): string {
  if (currentNote.includes(attempt.trim())) {
    return currentNote;
  }
  return `${currentNote.trim()}\n\n${attempt.trim()}`;
}

export function createMessage(
  speaker: ConversationMessage["speaker"],
  text: string,
  label?: string,
): ConversationMessage {
  messageCounter += 1;
  return {
    id: `msg-${messageCounter}`,
    speaker,
    text,
    label,
  };
}

export function computeSidebarProgress(plan: CreatedPlanResponse): number {
  if (plan.knowledge_points.length === 0) {
    return 0;
  }
  const progressed = plan.knowledge_points.filter((item) => item.status !== "pending").length;
  return progressed / plan.knowledge_points.length;
}

export function initialBlankState(exercise: LearningExercise): Record<string, string> {
  return Object.fromEntries(exercise.code_blanks.map((blank) => [blank.blank_key, ""]));
}

export function materializeExerciseCode(code: string, filledBlanks: Record<string, string>): string {
  return Object.entries(filledBlanks).reduce((currentCode, [blankKey, value]) => {
    const token = `__${blankKey.toUpperCase()}__`;
    return currentCode.replaceAll(token, value.trim() || token);
  }, code);
}

export function markKnowledgePointLearning(
  plan: CreatedPlanResponse,
  knowledgePointId: string,
): CreatedPlanResponse {
  return {
    ...plan,
    knowledge_points: plan.knowledge_points.map((knowledgePoint) =>
      knowledgePoint.id === knowledgePointId && !isReviewStatus(knowledgePoint.status)
        ? { ...knowledgePoint, status: "learning" }
        : knowledgePoint,
    ),
  };
}

function isReviewStatus(status: CreatedPlanResponse["knowledge_points"][number]["status"]): boolean {
  return status === "reviewing" || status === "mastered";
}

export function applyKnowledgePointUpdate(
  plan: CreatedPlanResponse,
  patch: SubmitExerciseResponse["KnowledgePoint"],
): CreatedPlanResponse {
  return {
    ...plan,
    knowledge_points: plan.knowledge_points.map((knowledgePoint) =>
      knowledgePoint.id === patch.id
        ? {
            ...knowledgePoint,
            status: patch.status,
            mastery_score: patch.mastery_score,
          }
        : knowledgePoint,
    ),
  };
}

export function toActionError(error: unknown): AsyncActionState {
  if (error instanceof ApiRequestError) {
    return {
      status: "error",
      code: error.apiError.code,
      message: error.apiError.message,
      recoverable: error.apiError.recoverable,
    };
  }
  return {
    status: "error",
    code: "CLIENT_ERROR",
    message: error instanceof Error ? error.message : "请求失败",
    recoverable: true,
  };
}
