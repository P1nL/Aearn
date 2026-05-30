import { ApiRequestError } from "../types";

export type ErrorInfo = {
  code: string;
  message: string;
  recoverable: boolean;
};

const ERROR_MESSAGES: Record<string, string> = {
  RUNNER_TIMEOUT: "代码运行超时，请简化代码后重试",
  RUNNER_UNAVAILABLE: "运行服务暂时不可用，请稍后重试",
  RUNTIME_UNSUPPORTED: "当前语言第一版不支持完整运行",
  SESSION_NOT_FOUND: "学习会话不存在，请重新开始",
  ATTEMPT_NOT_FOUND: "运行记录不存在",
  ATTEMPT_STATE_CONFLICT: "当前状态不允许此操作",
  IDEMPOTENCY_CONFLICT: "请求冲突，请刷新页面后重试",
  EVALUATION_CONFLICT: "评分结果冲突",
  NOTE_NOT_FOUND: "笔记不存在",
  VALIDATION_ERROR: "请求参数不合法",
  USER_NOT_FOUND: "用户不存在",
  PLAN_NOT_FOUND: "学习计划不存在",
  PLAN_DRAFT_INVALID: "计划草稿校验失败",
  COURSE_NOT_FOUND: "课程不存在",
  KNOWLEDGE_POINT_NOT_FOUND: "知识点不存在",
  EXERCISE_NOT_FOUND: "练习不存在",
  MODULE_NOT_FOUND: "模块不存在",
  MODULE_NOT_SKIPPABLE: "该模块不允许跳过",
  REVIEW_NOT_DUE: "知识点未到复习时间",
  REVIEW_SEED_BANK_GENERATION_FAILED: "复习材料生成失败，请稍后重试",
  SESSION_CONFLICT: "存在冲突的活动会话",
  EVALUATION_INVALID_JSON: "评分输出解析失败，请重试",
  CONCEPT_INTRO_GENERATION_FAILED: "概念开场生成失败，请重试生成或返回路线选择其他知识点",
  RATE_LIMITED: "操作过于频繁，请稍后重试",
  INTERNAL_ERROR: "服务端错误，请稍后重试",
};

export function getErrorInfo(error: unknown): ErrorInfo {
  if (error instanceof ApiRequestError) {
    return {
      code: error.apiError.code,
      message: ERROR_MESSAGES[error.apiError.code] ?? error.apiError.message,
      recoverable: error.apiError.recoverable,
    };
  }
  if (error instanceof Error) {
    return {
      code: "CLIENT_ERROR",
      message: error.message,
      recoverable: true,
    };
  }
  return {
    code: "UNKNOWN_ERROR",
    message: "未知错误",
    recoverable: false,
  };
}

export function formatErrorMessage(error: unknown, fallback: string): string {
  return getErrorInfo(error).message || fallback;
}
