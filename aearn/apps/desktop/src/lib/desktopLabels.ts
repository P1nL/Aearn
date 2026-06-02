import type { AppRoute, ExerciseRunMode, SettingsKey, WorkbenchState } from "../appTypes";
import type { CreatedKnowledgePoint, LearningExercise, LearningSessionResponse } from "../types";
import { ROUTE_META, SETTING_PANELS } from "./appContent";

export function screenClassName(active: boolean): string {
  return active ? "screen active" : "screen";
}

export function getCrumbLabel(
  route: AppRoute,
  settingsTab: SettingsKey,
  session: LearningSessionResponse | null,
  exercise: LearningExercise | null,
): string {
  if (route === "settings") {
    return `设置 / ${SETTING_PANELS[settingsTab].title}`;
  }
  if (route === "home" && session && exercise) {
    return `${session.context_snapshot.KnowledgePoint.title} / ${exercise.title}`;
  }
  return ROUTE_META[route].crumb;
}

export function runtimeLabel(runtimeTier: string): string {
  if (runtimeTier === "browser_preview") {
    return "浏览器预览 + DOM 断言";
  }
  if (runtimeTier === "python_stdout_test") {
    return "Python stdout + 可见测试";
  }
  if (runtimeTier === "node_typescript_test") {
    return "TypeScript 单文件函数测试";
  }
  if (runtimeTier === "sql_query_test") {
    return "SQLite 教学查询测试";
  }
  if (runtimeTier === "managed_compiled_test") {
    return "本机编译工具链 + 可见/隐藏测试";
  }
  return "编译沙箱后置";
}

export function runtimeStatusLabel(runtimeStatus: string): string {
  if (runtimeStatus === "missing_toolchain") {
    return "缺少本机工具链";
  }
  if (runtimeStatus === "compile_error") {
    return "编译错误";
  }
  if (runtimeStatus === "runtime_error") {
    return "运行错误";
  }
  if (runtimeStatus === "timeout") {
    return "执行超时";
  }
  if (runtimeStatus === "test_failure") {
    return "测试未通过";
  }
  if (runtimeStatus === "unsupported") {
    return "能力未开放";
  }
  return "运行成功";
}

export function nextActionLabel(nextAction: string): string {
  if (nextAction === "show_hint") {
    return "获取提示";
  }
  if (nextAction === "explain_error") {
    return "解释错误";
  }
  if (nextAction === "review_variant") {
    return "复习变体";
  }
  if (nextAction === "schedule_review") {
    return "进入复习";
  }
  if (nextAction === "advance_next") {
    return "继续下一步";
  }
  return "重新运行";
}

export function completionResultLabel(result: string): string {
  if (result === "easy") {
    return "轻松掌握";
  }
  if (result === "passed") {
    return "通过";
  }
  if (result === "partial") {
    return "部分通过";
  }
  if (result === "failed") {
    return "未通过";
  }
  return result;
}

export function fsrsRatingLabel(rating: string | number | null): string {
  if (rating === null) {
    return "未安排";
  }
  if (rating === "again" || rating === "Again" || rating === 1) {
    return "需要重学";
  }
  if (rating === "hard" || rating === "Hard" || rating === 2) {
    return "较困难";
  }
  if (rating === "good" || rating === "Good" || rating === 3) {
    return "良好";
  }
  if (rating === "easy" || rating === "Easy" || rating === 4) {
    return "轻松掌握";
  }
  return String(rating);
}

export function hardGateLabel(gate: string): string {
  if (gate === "runtime_gate") {
    return "运行边界";
  }
  if (gate === "test_gate") {
    return "测试通过";
  }
  if (gate === "core_blank_gate") {
    return "核心空缺";
  }
  if (gate === "explanation_gate") {
    return "解释检查";
  }
  return gate;
}

export function workbenchStateLabel(state: WorkbenchState): string {
  if (state === "dirty") {
    return "已修改";
  }
  if (state === "running") {
    return "运行中";
  }
  if (state === "submitted") {
    return "已提交";
  }
  if (state === "unsupported") {
    return "暂不支持";
  }
  return "就绪";
}

export function knowledgePointStatusLabel(status: CreatedKnowledgePoint["status"]): string {
  if (status === "reviewing") {
    return "进入复习";
  }
  if (status === "mastered") {
    return "已掌握";
  }
  if (status === "learning") {
    return "学习中";
  }
  return "待开始";
}
