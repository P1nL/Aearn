import type {
  AsyncActionState,
  ConversationMessage,
  DraftModuleCard,
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
import { knowledgePointStatusLabel, runtimeLabel, runtimeStatusLabel } from "./desktopLabels";

let messageCounter = 0;

export function buildLearnNavItems(plan: CreatedPlanResponse | null, activeKnowledgePointId: string): LearnNavItem[] {
  if (!plan) {
    return [
      { id: "learn-1", title: "DOM 事件补全", active: true },
      { id: "learn-2", title: "HTML / CSS 选择器", active: false },
      { id: "learn-3", title: "Python 函数测试", active: false },
    ];
  }

  return plan.knowledge_points.slice(0, 3).map((knowledgePoint, index) => ({
    id: knowledgePoint.id,
    title: knowledgePoint.title,
    active: knowledgePoint.id === activeKnowledgePointId || (index === 0 && activeKnowledgePointId.length === 0),
  }));
}

export function buildRouteCards(plan: CreatedPlanResponse | null, activeKnowledgePointId: string): RouteCard[] {
  if (!plan) {
    return [
      { id: "route-1", index: 1, title: "HTML / CSS 基础", body: "已完成 · 页面结构与选择器", active: false, knowledgePointId: "" },
      { id: "route-2", index: 2, title: "DOM 事件", body: "练习中 · 点击计数与状态变量", active: true, knowledgePointId: "" },
      { id: "route-3", index: 3, title: "Python 函数测试", body: "未开始 · 补全函数并运行断言", active: false, knowledgePointId: "" },
      { id: "route-4", index: 4, title: "AI 代码理解", body: "未开始 · 解释生成代码和报错", active: false, knowledgePointId: "" },
      { id: "route-5", index: 5, title: "调试小项目", body: "未开始 · 完整运行、测试和复盘", active: false, knowledgePointId: "" },
    ];
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
    return [
      { title: "事件函数内部重置状态", body: "遗忘风险 78%，今天必须复习。" },
      { title: "CSS 状态类选择错误", body: "遗忘风险 54%，建议今晚处理。" },
      { title: "Python 返回值边界判断", body: "明天到期，今天只展示预告。" },
    ];
  }

  return [
    {
      title: lastSubmit.code_completion_result.weak_points[0] ?? "状态变量生命周期",
      body: `最新评分 ${lastSubmit.code_completion_result.score} / 8，复习等级 ${lastSubmit.code_completion_result.fsrs_rating}。`,
    },
    {
      title: "运行结果",
      body: lastRun ? `可见测试通过 ${lastRun.passed_test_count}/${lastRun.total_test_count}。` : "本次提交未保留运行详情。",
    },
    {
      title: "下一步",
      body: `调度建议：${lastSubmit.next_action}，知识点状态已更新为 ${knowledgePointStatusLabel(lastSubmit.KnowledgePoint.status)}。`,
    },
  ];
}

export function buildFallbackDraftModules(): DraftModuleCard[] {
  return [
    { id: "draft-1", title: "HTML 结构与 CSS 选择器", description: "建立页面结构、选择器和实时预览的共同语言", tag: "保留", tagClass: "tag strong" },
    { id: "draft-2", title: "JavaScript DOM 事件", description: "理解事件监听、状态变量和输出更新", tag: "主干", tagClass: "tag warn" },
    { id: "draft-3", title: "Python 函数与测试", description: "将补全结果与断言、测试反馈连接", tag: "新增", tagClass: "tag" },
    { id: "draft-4", title: "AI 生成代码理解", description: "识别关键路径、冗余代码和可验证修改", tag: "可压缩", tagClass: "tag" },
    { id: "draft-5", title: "调试一个小型页面", description: "用完整练习完成运行、测试和复盘", tag: "终局", tagClass: "tag" },
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

Attempt 记录：
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
    lines.push("", `Run: ${runtimeStatusLabel(lastRun.runtime_status)}，通过 ${lastRun.passed_test_count}/${lastRun.total_test_count}。`);
    if (lastRun.error_message) {
      lines.push(`错误：${lastRun.error_message}`);
    }
  }
  if (lastSubmit) {
    lines.push("", `Submit: ${lastSubmit.code_completion_result.result}，评分 ${lastSubmit.code_completion_result.score}/8。`);
    lines.push(`反馈：${lastSubmit.code_completion_result.feedback}`);
  }
  if (!lastRun && !lastSubmit) {
    lines.push("", "Attempt 1：先补全最小代码，再运行可见测试。");
  }
  return lines.join("\n");
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
      knowledgePoint.id === knowledgePointId ? { ...knowledgePoint, status: "learning" } : knowledgePoint,
    ),
  };
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
