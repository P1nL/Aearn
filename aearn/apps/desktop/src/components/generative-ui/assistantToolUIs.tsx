import { makeAssistantToolUI, type ToolCallMessagePartProps } from "@assistant-ui/react";
import { createContext, useContext, type ReactNode } from "react";

import { LearningRouteCard } from "./LearningRouteCard";
import type {
  CodeExerciseToolArgs,
  ConceptCheck,
  ConceptCheckResultArgs,
  ConceptIntroArgs,
  LearningHistoryArgs,
  LearningRouteArgs,
  ToolUIProps,
} from "./types";

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
  time_budget: null,
  modules: [],
};

type LearningToolRuntime = {
  renderCodeExercise?: (
    args: CodeExerciseToolArgs | null,
    status: ToolStatus,
  ) => ReactNode;
};

const LearningToolRuntimeContext = createContext<LearningToolRuntime>({});

type LearningRouteRuntime = {
  latestToolCallId: string | null;
};

const LearningRouteRuntimeContext = createContext<LearningRouteRuntime>({
  latestToolCallId: null,
});

export function LearningToolRuntimeProvider({
  runtime,
  children,
}: {
  runtime: LearningToolRuntime;
  children: ReactNode;
}) {
  return (
    <LearningToolRuntimeContext.Provider value={runtime}>
      {children}
    </LearningToolRuntimeContext.Provider>
  );
}

export function LearningRouteRuntimeProvider({
  latestToolCallId,
  children,
}: {
  latestToolCallId: string | null;
  children: ReactNode;
}) {
  return (
    <LearningRouteRuntimeContext.Provider value={{ latestToolCallId }}>
      {children}
    </LearningRouteRuntimeContext.Provider>
  );
}

function isPartialLearningRouteArgs(value: unknown): value is Partial<LearningRouteArgs> {
  return typeof value === "object" && value !== null;
}

function normalizeLearningRouteArgs(args: unknown): LearningRouteArgs {
  if (!isPartialLearningRouteArgs(args)) {
    return EMPTY_LEARNING_ROUTE;
  }
  const rawTimeBudget = args.time_budget;
  const timeBudget =
    isRecord(rawTimeBudget) &&
    typeof rawTimeBudget.minutes_per_day === "number" &&
    typeof rawTimeBudget.days_per_week === "number"
      ? {
          minutes_per_day: rawTimeBudget.minutes_per_day,
          days_per_week: rawTimeBudget.days_per_week,
        }
      : null;
  return {
    plan_id: typeof args.plan_id === "string" ? args.plan_id : EMPTY_LEARNING_ROUTE.plan_id,
    goal_text: typeof args.goal_text === "string" ? args.goal_text : EMPTY_LEARNING_ROUTE.goal_text,
    language: (args.language as LearningRouteArgs["language"]) ?? EMPTY_LEARNING_ROUTE.language,
    time_budget: timeBudget,
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

function dispatchLearningRouteAction(action: string, payload?: unknown) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent("aearn:learning-route-action", {
      detail: { action, payload },
    }),
  );
}

export const LearningRouteToolUI = makeAssistantToolUI<LearningRouteArgs, unknown>({
  toolName: "show_learning_route",
  render: ({ args, status, toolCallId }) => {
    const runtime = useContext(LearningRouteRuntimeContext);
    const normalized = normalizeLearningRouteArgs(args);
    const cardStatus = mapStatusToToolStatus(status);
    const canStart =
      runtime.latestToolCallId === null || runtime.latestToolCallId === toolCallId;
    return (
      <LearningRouteCard
        args={normalized}
        status={cardStatus}
        canStart={canStart}
        onAction={dispatchLearningRouteAction}
      />
    );
  },
});

export const CodeExerciseToolUI = makeAssistantToolUI<CodeExerciseToolArgs, unknown>({
  toolName: "show_code_exercise",
  render: ({ args, status }) => {
    const runtime = useContext(LearningToolRuntimeContext);
    const cardStatus = mapStatusToToolStatus(status);
    const normalized = normalizeCodeExerciseArgs(args);
    if (runtime.renderCodeExercise) {
      return <>{runtime.renderCodeExercise(normalized, cardStatus)}</>;
    }
    if (!normalized) {
      return <div className="tool-card">正在生成练习卡片…</div>;
    }
    return (
      <article className="gen-card gen-exercise-card">
        <header className="gen-card-header">
          <span className="gen-card-kicker">练习已解锁</span>
          <span className="gen-card-badge">{normalized.exercise.runtime_profile.language}</span>
        </header>
        <h3 className="gen-card-title">{normalized.exercise.title}</h3>
        <p>{normalized.notice}</p>
      </article>
    );
  },
});

export const ConceptIntroToolUI = makeAssistantToolUI<ConceptIntroArgs, unknown>({
  toolName: "show_concept_intro",
  render: ({ args, status }) => (
    <ConceptIntroCard
      args={normalizeConceptIntroArgs(args)}
      status={mapStatusToToolStatus(status)}
    />
  ),
});

export const ConceptCheckResultToolUI = makeAssistantToolUI<ConceptCheckResultArgs, unknown>({
  toolName: "show_concept_check_result",
  render: ({ args, status }) => (
    <ConceptCheckResultCard
      args={normalizeConceptCheckResultArgs(args)}
      status={mapStatusToToolStatus(status)}
    />
  ),
});

export const LearningHistoryToolUI = makeAssistantToolUI<LearningHistoryArgs, unknown>({
  toolName: "show_learning_history",
  render: ({ args, status }) => (
    <LearningHistoryCard
      args={normalizeLearningHistoryArgs(args)}
      status={mapStatusToToolStatus(status)}
    />
  ),
});

function normalizeCodeExerciseArgs(args: unknown): CodeExerciseToolArgs | null {
  if (!isRecord(args) || !isRecord(args.exercise)) {
    return null;
  }
  const exercise = args.exercise as CodeExerciseToolArgs["exercise"];
  if (typeof exercise.id !== "string" || !isRecord(exercise.runtime_profile)) {
    return null;
  }
  return {
    session_id: typeof args.session_id === "string" ? args.session_id : "",
    knowledge_point_id: typeof args.knowledge_point_id === "string" ? args.knowledge_point_id : "",
    exercise,
    unlock_reason: typeof args.unlock_reason === "string" ? args.unlock_reason : null,
    learning_incomplete: Boolean(args.learning_incomplete),
    concept_summary: typeof args.concept_summary === "string" ? args.concept_summary : "",
    notice: typeof args.notice === "string" ? args.notice : "",
  };
}

function normalizeLearningHistoryArgs(args: unknown): LearningHistoryArgs {
  if (!isRecord(args)) {
    return {
      knowledge_point_id: "",
      knowledge_point_title: "当前知识点",
      active_session_id: null,
      sessions: [],
    };
  }
  const sessions = Array.isArray(args.sessions)
    ? args.sessions
        .filter((session): session is Record<string, unknown> => isRecord(session))
        .map((session) => ({
          session_id: typeof session.session_id === "string" ? session.session_id : "",
          is_active: Boolean(session.is_active),
          status: typeof session.status === "string" ? session.status : "",
          started_at: typeof session.started_at === "string" ? session.started_at : null,
          messages: Array.isArray(session.messages)
            ? session.messages
                .filter((message): message is Record<string, unknown> => isRecord(message))
                .map((message) => ({
                  id: typeof message.id === "string" ? message.id : "",
                  role: message.role === "user" ? "user" as const : "agent" as const,
                  content: typeof message.content === "string" ? message.content : "",
                  created_at: typeof message.created_at === "string" ? message.created_at : null,
                }))
            : [],
        }))
    : [];
  return {
    knowledge_point_id: typeof args.knowledge_point_id === "string" ? args.knowledge_point_id : "",
    knowledge_point_title:
      typeof args.knowledge_point_title === "string" ? args.knowledge_point_title : "当前知识点",
    active_session_id: typeof args.active_session_id === "string" ? args.active_session_id : null,
    sessions,
  };
}

function LearningHistoryCard({
  args,
  status,
}: ToolUIProps<LearningHistoryArgs>) {
  return (
    <article className="gen-card learning-history-card" aria-label="相关学习对话">
      <header className="gen-card-header">
        <span className="gen-card-kicker">相关学习对话</span>
        <span className="gen-card-badge">
          {status === "running" ? "加载中" : `${args.sessions.length} 个会话`}
        </span>
      </header>
      <h3 className="gen-card-title">{args.knowledge_point_title}</h3>
      <p className="learning-history-intro">
        这里只引用学习页 AI/用户对话，不包含建档页和复习页内容。先回看关键说法，再重新用费曼方式解释。
      </p>
      <div className="learning-history-sessions">
        {args.sessions.length === 0 ? (
          <div className="empty-block">当前知识点还没有可引用的学习对话。</div>
        ) : (
          args.sessions.map((session) => (
            <details className="learning-history-session" key={session.session_id} open={session.is_active}>
              <summary>
                <span>{session.is_active ? "当前会话" : "历史会话"}</span>
                <span>{session.started_at ? new Date(session.started_at).toLocaleString("zh-CN") : session.status}</span>
              </summary>
              <div className="learning-history-turns">
                {session.messages.map((message) => (
                  <blockquote className={`learning-history-turn ${message.role}`} key={message.id}>
                    <strong>{message.role === "user" ? "你" : "AI"}</strong>
                    <span>{message.content}</span>
                  </blockquote>
                ))}
              </div>
            </details>
          ))
        )}
      </div>
    </article>
  );
}

function normalizeConceptIntroArgs(args: unknown): ConceptIntroArgs {
  if (!isRecord(args)) {
    return EMPTY_CONCEPT_INTRO;
  }
  return {
    session_id: typeof args.session_id === "string" ? args.session_id : "",
    knowledge_point_id: typeof args.knowledge_point_id === "string" ? args.knowledge_point_id : "",
    summary: typeof args.summary === "string" ? args.summary : "正在生成概念摘要…",
    example: normalizeConceptExample(args.example),
    check: normalizeConceptCheck(args.check),
  };
}

function normalizeConceptCheckResultArgs(args: unknown): ConceptCheckResultArgs {
  if (!isRecord(args)) {
    return EMPTY_CONCEPT_CHECK_RESULT;
  }
  return {
    session_id: typeof args.session_id === "string" ? args.session_id : "",
    knowledge_point_id: typeof args.knowledge_point_id === "string" ? args.knowledge_point_id : "",
    result: isConceptResult(args.result) ? args.result : "unclear",
    confidence: isConfidence(args.confidence) ? args.confidence : "low",
    explanation: typeof args.explanation === "string" ? args.explanation : "",
    next_prompt: typeof args.next_prompt === "string" ? args.next_prompt : "",
    actions: Array.isArray(args.actions)
      ? args.actions
          .filter((action): action is Record<string, unknown> => isRecord(action))
          .map((action) => ({
            id: typeof action.id === "string" ? action.id : "",
            label: typeof action.label === "string" ? action.label : "",
          }))
          .filter((action) => action.id && action.label)
      : [],
    repair_check: isRecord(args.repair_check) ? normalizeConceptCheck(args.repair_check) : null,
  };
}

const EMPTY_CONCEPT_CHECK: ConceptCheck = {
  type: "single_choice",
  question: "这个概念判断题还在生成中。",
  options: [],
  expected_focus: "",
};

const EMPTY_CONCEPT_INTRO: ConceptIntroArgs = {
  session_id: "",
  knowledge_point_id: "",
  summary: "正在生成概念摘要…",
  example: {
    title: "例子生成中",
    body: "稍等片刻，Agent 会给出一个更容易理解的小例子。",
    takeaway: "先看概念关系，再进入练习。",
  },
  check: EMPTY_CONCEPT_CHECK,
};

const EMPTY_CONCEPT_CHECK_RESULT: ConceptCheckResultArgs = {
  session_id: "",
  knowledge_point_id: "",
  result: "unclear",
  confidence: "low",
  explanation: "这次判断结果还在生成中。",
  next_prompt: "请稍等或重新发送你的回答。",
  actions: [],
  repair_check: null,
};

function normalizeConceptExample(value: unknown): ConceptIntroArgs["example"] {
  if (!isRecord(value)) {
    return EMPTY_CONCEPT_INTRO.example;
  }
  return {
    title: typeof value.title === "string" ? value.title : "小例子",
    body: typeof value.body === "string" ? value.body : "",
    takeaway: typeof value.takeaway === "string" ? value.takeaway : "",
  };
}

function normalizeConceptCheck(value: unknown): ConceptCheck {
  if (!isRecord(value)) {
    return EMPTY_CONCEPT_CHECK;
  }
  return {
    type: "single_choice",
    question: typeof value.question === "string" ? value.question : EMPTY_CONCEPT_CHECK.question,
    options: Array.isArray(value.options)
      ? value.options
          .filter((option): option is Record<string, unknown> => isRecord(option))
          .map((option, index) => ({
            id: typeof option.id === "string" ? option.id : String.fromCharCode(65 + index),
            text: typeof option.text === "string" ? option.text : "",
          }))
          .filter((option) => option.text)
      : [],
    expected_focus: typeof value.expected_focus === "string" ? value.expected_focus : "",
  };
}

function ConceptIntroCard({
  args,
  status,
}: ToolUIProps<ConceptIntroArgs>) {
  return (
    <article className="gen-card concept-intro-card" aria-label="概念开场判断">
      <header className="gen-card-header">
        <span className="gen-card-kicker">概念先行</span>
        <span className={status === "running" ? "gen-card-badge streaming" : "gen-card-badge"}>
          {status === "running" ? "生成中" : "回答可直接打字"}
        </span>
      </header>
      <h3 className="gen-card-title">先判断一个小关系</h3>
      <p className="concept-summary">{args.summary}</p>
      <section className="concept-example" aria-label="概念例子">
        <strong>{args.example.title}</strong>
        <p>{args.example.body}</p>
        {args.example.takeaway && <span>{args.example.takeaway}</span>}
      </section>
      <section className="concept-check" aria-label="判断题">
        <p>{args.check.question}</p>
        <div className="concept-options">
          {args.check.options.map((option) => (
            <div className="concept-option" key={option.id}>
              <span>{option.id}</span>
              <p>{option.text}</p>
            </div>
          ))}
        </div>
        <small>你可以回复选项字母，也可以用自己的话说明判断。</small>
      </section>
    </article>
  );
}

function ConceptCheckResultCard({
  args,
  status,
}: ToolUIProps<ConceptCheckResultArgs>) {
  const resultLabel = conceptResultLabel(args.result);
  return (
    <article className={`gen-card concept-result-card ${args.result}`} aria-label="概念判断结果">
      <header className="gen-card-header">
        <span className="gen-card-kicker">判断结果</span>
        <span className={status === "running" ? "gen-card-badge streaming" : "gen-card-badge"}>
          {status === "running" ? "判断中" : `${resultLabel} · ${confidenceLabel(args.confidence)}`}
        </span>
      </header>
      <h3 className="gen-card-title">{resultLabel}</h3>
      <p>{args.explanation}</p>
      {args.repair_check && (
        <section className="concept-check repair" aria-label="修复判断题">
          <p>{args.repair_check.question}</p>
          <div className="concept-options">
            {args.repair_check.options.map((option) => (
              <div className="concept-option" key={option.id}>
                <span>{option.id}</span>
                <p>{option.text}</p>
              </div>
            ))}
          </div>
        </section>
      )}
      {args.next_prompt && <p className="concept-next">{args.next_prompt}</p>}
      {args.actions.length > 0 && (
        <div className="concept-action-hints" aria-label="可回复动作">
          {args.actions.map((action) => (
            <span key={action.id}>{action.label}</span>
          ))}
        </div>
      )}
    </article>
  );
}

function conceptResultLabel(result: ConceptCheckResultArgs["result"]): string {
  switch (result) {
    case "correct":
      return "理解基本到位";
    case "incorrect":
      return "先修正一个误解";
    case "skipped":
      return "已跳过概念检查";
    case "unclear":
    default:
      return "还需要更具体一点";
  }
}

function confidenceLabel(confidence: ConceptCheckResultArgs["confidence"]): string {
  if (confidence === "high") return "高置信";
  if (confidence === "medium") return "中置信";
  return "低置信";
}

function isConceptResult(value: unknown): value is ConceptCheckResultArgs["result"] {
  return value === "correct" || value === "incorrect" || value === "unclear" || value === "skipped";
}

function isConfidence(value: unknown): value is ConceptCheckResultArgs["confidence"] {
  return value === "high" || value === "medium" || value === "low";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
