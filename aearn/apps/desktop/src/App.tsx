import { startTransition, useDeferredValue, useEffect, useState } from "react";

import {
  checkLearningExplanation,
  confirmPlan,
  createUser,
  explainLearningError,
  fetchApiHealth,
  fetchLanguageCourses,
  generatePlanDraft,
  requestLearningHint,
  runLearningExercise,
  startLearningSession,
  submitLearningExercise,
} from "./api";
import { ApiRequestError } from "./types";
import type {
  ApiHealth,
  CreatedKnowledgePoint,
  CreatedPlanResponse,
  ExplainErrorResponse,
  ExplanationFocus,
  ExplanationCheckResponse,
  HintLevel,
  HintResponse,
  LanguageCourse,
  LearningExercise,
  LearningMode,
  LearningSessionResponse,
  PlanDraft,
  RunExerciseResponse,
  SubmitExerciseResponse,
  UserProfile,
} from "./types";

type ApiHealthState =
  | { status: "loading" }
  | { status: "online"; data: ApiHealth }
  | { status: "offline"; message: string };

type AsyncActionState =
  | { status: "idle" }
  | { status: "loading"; label: string }
  | { status: "error"; code: string; message: string; recoverable: boolean };

type SessionState =
  | { status: "idle" }
  | { status: "loading"; knowledgePointId: string }
  | { status: "ready"; data: LearningSessionResponse }
  | { status: "error"; knowledgePointId: string | null; message: string };

type ExerciseActionKind =
  | "run_preview"
  | "run_tests"
  | "submit"
  | "hint"
  | "explain_error"
  | "check_explanation";

type AppRoute = "onboarding" | "home" | "review" | "notes" | "settings";
type SettingsKey = "appearance" | "model" | "notification" | "memory" | "notes" | "about";
type PublishKey = "review" | "solution" | "prompt" | "interview";
type NavGroupKey = "learn" | "review" | "notes" | "notes-python" | "notes-javascript" | "notes-sql";

type ConversationMessage = {
  id: string;
  speaker: "agent" | "user";
  text: string;
  label?: string;
  toolCard?: string;
};

type SettingsPanel = {
  title: string;
  meta: string;
  cards: [string, string][];
};

const ROUTE_META: Record<AppRoute, { crumb: string; hint: string }> = {
  onboarding: {
    crumb: "首次建档 / 实时课程生成",
    hint: "首次使用完成建档后进入学习页",
  },
  home: {
    crumb: "JavaScript DOM / 事件补全",
    hint: "今晚 20:30 继续",
  },
  review: {
    crumb: "复习 / DOM 状态生命周期",
    hint: "复习完成后更新 due_at",
  },
  notes: {
    crumb: "笔记 / JavaScript / DOM 事件补全",
    hint: "Markdown 笔记可编辑",
  },
  settings: {
    crumb: "设置 / 外观",
    hint: "设置影响 Agent 上下文和提醒策略",
  },
};

const SETTING_PANELS: Record<SettingsKey, SettingsPanel> = {
  appearance: {
    title: "外观",
    meta: "控制桌面端视觉密度和主题偏好",
    cards: [
      ["主题", "奶油色 Claude Desktop 风格"],
      ["内容密度", "宽松，减少学习焦虑"],
      ["动效", "轻量淡入和抽屉滑入"],
      ["侧栏", "默认展开，可折叠"],
    ],
  },
  model: {
    title: "模型设置",
    meta: "配置代码提示、复习变体、错因解释和复盘草稿所用模型",
    cards: [
      ["提示模型", "用于日常代码练习会话"],
      ["测试解释模型", "用于解释失败用例与报错"],
      ["复盘模型", "用于题解和 AI 协作提示词草稿"],
      ["工具调用", "只在明确需要时启用"],
    ],
  },
  notification: {
    title: "通知设置",
    meta: "控制学习提醒和复习到期提示",
    cards: [
      ["学习提醒", "工作日 20:30"],
      ["复习优先", "due_at 到期时优先提示"],
      ["中断恢复", "多日未学时展示阶段摘要"],
      ["外部通知", "第一版默认关闭"],
    ],
  },
  memory: {
    title: "Attempt 记录配置",
    meta: "配置原始 Attempt、测试结果、错因标签和复习状态的保存位置",
    cards: [
      ["原始 Attempt", "保存提交代码、运行输出和测试结果"],
      ["阶段摘要", "按模块生成可恢复练习上下文"],
      ["错因记忆", "绑定掌握度、复习状态和变体题"],
      ["隐私策略", "不自动外传本地文件"],
    ],
  },
  notes: {
    title: "练习设置",
    meta: "控制 Attempt 分类、自动保存和复盘草稿偏好",
    cards: [
      ["分类层级", "语言大类 / 练习点"],
      ["自动保存", "编辑时保存 Attempt 状态"],
      ["默认草稿类型", "复盘"],
      ["导出方式", "只生成草稿，手动复制"],
    ],
  },
  about: {
    title: "关于",
    meta: "Aearn 桌面端原型信息",
    cards: [
      ["版本", "V1 桌面端原型"],
      ["定位", "代码补全、运行预览、测试判定、复习变体闭环"],
      ["技术形态", "React + Vite + Tauri"],
      ["范围", "当前实现对齐 docs/design 原型结构"],
    ],
  },
};

const RETROSPECTIVE_DRAFTS: Record<PublishKey, { label: string; text: string }> = {
  review: {
    label: "复盘格式",
    text: `今天复盘 DOM 点击计数题，终于把状态变量位置和事件函数边界分清了。

错误：把 \`count\` 写进 click 回调内部，每次点击都会重置。
修正：把 \`count\` 放在监听器外层，回调只负责累加和更新输出。

测试：连续点击 3 次，输出应该显示 3。

下次问 AI：请先指出状态变量位置和测试用例，不要直接给完整答案。`,
  },
  solution: {
    label: "题解格式",
    text: `这道 DOM 点击计数题的关键不是 \`addEventListener\` 本身，而是状态变量的生命周期。\`count\` 如果写在点击回调内部，每次点击都会重新初始化；应该把它放到监听器外层，让多次点击共享同一个变量。验证方式是连续点击三次，输出依次变成 1、2、3。`,
  },
  prompt: {
    label: "AI 提示词格式",
    text: `请帮我调试一个 JavaScript DOM 点击计数练习。要求：

1. 先检查状态变量是否放在正确作用域。
2. 只给 hint 和失败原因，不要直接给完整答案。
3. 用测试用例说明为什么连续点击三次应该输出 3。
4. 如果需要代码，只给最小修改片段。`,
  },
  interview: {
    label: "面试讲述格式",
    text: `我会这样解释这道题：事件监听器会在每次点击时执行回调，如果把 \`count\` 声明在回调内部，每次执行都会从 0 开始。把 \`count\` 放在外层后，回调形成闭包，每次点击都能读写同一个状态，所以连续点击才会累加。`,
  },
};

const ONBOARDING_MESSAGES: ConversationMessage[] = [
  {
    id: "onboarding-agent-1",
    speaker: "agent",
    label: "Agent",
    text: "先告诉我你想学哪门语言，以及你希望学完后能独立完成什么代码任务。",
  },
  {
    id: "onboarding-user-1",
    speaker: "user",
    text: "我想系统学 JavaScript/HTML/CSS 和一点 Python，能看懂 AI 生成代码、自己补全交互并用测试验证。",
  },
  {
    id: "onboarding-agent-2",
    speaker: "agent",
    label: "Agent",
    text: "我会先把路线拆成 HTML/CSS 基础、DOM 事件、Python 函数测试、AI 生成代码理解、调试小项目五段。右侧会随着澄清实时更新。",
  },
];

const HOME_BASE_MESSAGES: ConversationMessage[] = [
  {
    id: "home-agent-1",
    speaker: "agent",
    label: "Agent",
    text: "先找到按钮和输出节点，再补事件监听。不要直接复制 AI 完整答案，先写最小可运行代码。",
    toolCard: "当前练习：DOM 点击计数 · 测试 2/3",
  },
  {
    id: "home-user-1",
    speaker: "user",
    text: "我把 `let count = 0` 写在点击函数里，为什么测试说连续点击失败？",
  },
  {
    id: "home-agent-2",
    speaker: "agent",
    label: "Agent",
    text: "因为每次点击都会重新创建 `count`。把它移到监听器外层，让多次点击共享同一个状态，再运行测试验证。",
  },
];

const REVIEW_BASE_MESSAGES: ConversationMessage[] = [
  {
    id: "review-agent-1",
    speaker: "agent",
    label: "Agent",
    text: "把“按钮点击计数”迁移成“输入框字数统计”，并解释为什么状态变量不能放进事件函数内部。",
    toolCard: "复习目标：事件状态生命周期 · 遗忘风险 78%",
  },
  {
    id: "review-user-1",
    speaker: "user",
    text: "状态变量要放在监听器外层，事件触发时只更新它；如果放进函数内部，每次输入都会重新初始化。",
  },
];

const DEFAULT_NOTE_CONTENT = `# DOM 点击计数

Attempt 1:
把 \`let count = 0\` 写在 click 回调内部，连续点击测试失败。

Attempt 2:
把 \`count\` 放到监听器外层，click 回调只负责累加和更新 \`textContent\`。

测试结果：
1. 初始值显示 0，通过。
2. 点击一次显示 1，通过。
3. 连续点击三次显示 3，通过。

错因：
状态变量放进事件函数内部会在每次事件触发时重新初始化。`;

const DEFAULT_ATTEMPT_NOTE = "Attempt 2：把 `count` 移到事件函数外层，连续点击测试通过。错因：状态变量不能在每次事件触发时重新初始化。";

const NAV_DEFAULTS: Record<NavGroupKey, boolean> = {
  learn: true,
  review: true,
  notes: false,
  "notes-python": false,
  "notes-javascript": false,
  "notes-sql": false,
};

let messageCounter = 0;

function App() {
  const [apiHealth, setApiHealth] = useState<ApiHealthState>({ status: "loading" });
  const [courses, setCourses] = useState<LanguageCourse[]>([]);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [planDraft, setPlanDraft] = useState<PlanDraft | null>(null);
  const [createdPlan, setCreatedPlan] = useState<CreatedPlanResponse | null>(null);
  const [actionState, setActionState] = useState<AsyncActionState>({ status: "idle" });
  const [sessionState, setSessionState] = useState<SessionState>({ status: "idle" });
  const [exerciseActionState, setExerciseActionState] = useState<AsyncActionState>({ status: "idle" });
  const [displayName, setDisplayName] = useState("Pinking");
  const [mode, setMode] = useState<LearningMode>("goal_based");
  const [goalText, setGoalText] = useState("两周内掌握 DOM 事件，并能验证 AI 生成代码。");
  const [materialTitle, setMaterialTitle] = useState("已有学习材料");
  const [materialContent, setMaterialContent] = useState("");
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [editorCode, setEditorCode] = useState("");
  const [filledBlanks, setFilledBlanks] = useState<Record<string, string>>({});
  const [lastRun, setLastRun] = useState<RunExerciseResponse | null>(null);
  const [lastSubmit, setLastSubmit] = useState<SubmitExerciseResponse | null>(null);
  const [isStale, setIsStale] = useState(false);
  const [lastRunMode, setLastRunMode] = useState<"preview" | "visible_tests" | null>(null);
  const [lastExerciseAction, setLastExerciseAction] = useState<ExerciseActionKind | null>(null);
  const [hintUsageCount, setHintUsageCount] = useState(0);
  const [errorCount, setErrorCount] = useState(0);
  const [hintLevel, setHintLevel] = useState<HintLevel>("nudge");
  const [selectedBlankId, setSelectedBlankId] = useState("");
  const [hintHistory, setHintHistory] = useState<HintResponse[]>([]);
  const [explainErrorResult, setExplainErrorResult] = useState<ExplainErrorResponse | null>(null);
  const [explanationText, setExplanationText] = useState("");
  const [explanationFocus, setExplanationFocus] = useState<ExplanationFocus>("core_logic");
  const [explanationRound, setExplanationRound] = useState(1);
  const [explanationCheckResult, setExplanationCheckResult] = useState<ExplanationCheckResponse | null>(null);
  const [activeRoute, setActiveRoute] = useState<AppRoute>("onboarding");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [openGroups, setOpenGroups] = useState<Record<NavGroupKey, boolean>>(NAV_DEFAULTS);
  const [noteDrawerOpen, setNoteDrawerOpen] = useState(false);
  const [publishDrawerOpen, setPublishDrawerOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsKey>("appearance");
  const [publishDraftType, setPublishDraftType] = useState<PublishKey>("review");
  const [publishState, setPublishState] = useState(RETROSPECTIVE_DRAFTS.review.label);
  const [publishEditor, setPublishEditor] = useState(RETROSPECTIVE_DRAFTS.review.text);
  const [noteContent, setNoteContent] = useState(DEFAULT_NOTE_CONTENT);
  const [noteDrawerText, setNoteDrawerText] = useState(DEFAULT_ATTEMPT_NOTE);
  const [noteSaveState, setNoteSaveState] = useState("已保存");
  const [composerInput, setComposerInput] = useState("");
  const [homeConversation, setHomeConversation] = useState<ConversationMessage[]>([]);
  const [reviewConversation, setReviewConversation] = useState<ConversationMessage[]>([]);
  const deferredGoalText = useDeferredValue(goalText);
  const selectedCourse = courses.find((course) => course.id === selectedCourseId) ?? courses[0] ?? null;
  const session = sessionState.status === "ready" ? sessionState.data : null;
  const activeExercise = session?.exercise ?? null;
  const activeKnowledgePointId =
    sessionState.status === "ready"
      ? sessionState.data.context_snapshot.KnowledgePoint.id
      : sessionState.status === "loading"
        ? sessionState.knowledgePointId
        : sessionState.status === "error"
          ? (sessionState.knowledgePointId ?? "")
          : "";
  const canGenerate =
    apiHealth.status === "online" &&
    selectedCourse !== null &&
    displayName.trim().length > 0 &&
    (mode === "goal_based" ? goalText.trim().length > 0 : materialContent.trim().length > 0);
  const isBusy =
    actionState.status === "loading" ||
    exerciseActionState.status === "loading" ||
    sessionState.status === "loading";
  const visibleRoute = activeRoute;
  const currentSettingsPanel = SETTING_PANELS[settingsTab];
  const sidebarHint = ROUTE_META[visibleRoute].hint;
  const sidebarProgress = createdPlan ? computeSidebarProgress(createdPlan) : 0;
  const crumb = getCrumbLabel(visibleRoute, settingsTab, session, activeExercise);
  const homeMessages = [...HOME_BASE_MESSAGES, ...homeConversation];
  const reviewMessages = [...REVIEW_BASE_MESSAGES, ...reviewConversation];

  async function bootstrap(signal?: AbortSignal) {
    setApiHealth({ status: "loading" });
    setActionState({ status: "idle" });

    try {
      const [health, catalog] = await Promise.all([fetchApiHealth(signal), fetchLanguageCourses(signal)]);
      startTransition(() => {
        setApiHealth({ status: "online", data: health });
        setCourses(catalog);
        setSelectedCourseId((current) => current || catalog[0]?.id || "");
      });
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      setApiHealth({
        status: "offline",
        message: error instanceof Error ? error.message : "Unable to reach API service",
      });
    }
  }

  async function ensureUser(): Promise<UserProfile> {
    if (user) {
      return user;
    }
    const created = await createUser(displayName.trim());
    setUser(created);
    return created;
  }

  async function openLearningSession(planResponse: CreatedPlanResponse, knowledgePointId: string) {
    setSessionState({ status: "loading", knowledgePointId });
    try {
      const activeUser = await ensureUser();
      const response = await startLearningSession({
        userId: activeUser.id,
        planId: planResponse.LearningPlan.id,
        knowledgePointId,
      });
      startTransition(() => {
        setSessionState({ status: "ready", data: response });
        setCreatedPlan((current) => (current ? markKnowledgePointLearning(current, knowledgePointId) : current));
        setEditorCode(response.exercise.starter_code);
        setFilledBlanks(initialBlankState(response.exercise));
        setLastRun(null);
        setLastSubmit(null);
        setIsStale(false);
        setLastRunMode(null);
        setLastExerciseAction(null);
        setHintUsageCount(0);
        setErrorCount(0);
        setSelectedBlankId(response.exercise.code_blanks[0]?.blank_key ?? "");
        setHintHistory([]);
        setExplainErrorResult(null);
        setExplanationText("");
        setExplanationFocus("core_logic");
        setExplanationRound(1);
        setExplanationCheckResult(null);
        setExerciseActionState({ status: "idle" });
        setActiveRoute("home");
      });
    } catch (error) {
      setSessionState({
        status: "error",
        knowledgePointId,
        message: error instanceof Error ? error.message : "无法启动学习会话",
      });
    }
  }

  async function handleGenerate() {
    if (!selectedCourse || !canGenerate) {
      return;
    }
    setActionState({ status: "loading", label: "正在生成计划草稿" });
    try {
      const activeUser = await ensureUser();
      const draft = await generatePlanDraft({
        userId: activeUser.id,
        mode,
        courseId: selectedCourse.id,
        language: selectedCourse.language,
        goalText: deferredGoalText.trim(),
        materialTitle: materialTitle.trim(),
        materialContent: materialContent.trim(),
      });
      startTransition(() => {
        setPlanDraft(draft);
        setCreatedPlan(null);
        setSessionState({ status: "idle" });
        setActionState({ status: "idle" });
      });
    } catch (error) {
      setActionState(toActionError(error));
    }
  }

  async function handleConfirm() {
    if (!planDraft) {
      await handleGenerate();
      return;
    }
    setActionState({ status: "loading", label: "正在确认正式学习计划" });
    try {
      const activeUser = await ensureUser();
      const response = await confirmPlan(activeUser.id, planDraft);
      startTransition(() => {
        setCreatedPlan(response);
        setActionState({ status: "idle" });
      });
      const nextKnowledgePointId = response.next_entry_point.knowledge_point_id;
      if (nextKnowledgePointId) {
        await openLearningSession(response, nextKnowledgePointId);
      } else {
        setActiveRoute("home");
      }
    } catch (error) {
      setActionState(toActionError(error));
    }
  }

  async function handleRunExercise(runMode: "preview" | "visible_tests") {
    if (!session || !activeExercise) {
      return;
    }
    setLastExerciseAction(runMode === "preview" ? "run_preview" : "run_tests");
    const materializedCode = materializeExerciseCode(editorCode, filledBlanks);
    setExerciseActionState({
      status: "loading",
      label: runMode === "preview" ? "正在返回浏览器预览" : "正在运行可见测试",
    });
    try {
      const response = await runLearningExercise({
        sessionId: session.session_id,
        exerciseId: activeExercise.id,
        code: materializedCode,
        filledBlanks,
        runtimeProfileId: activeExercise.runtime_profile.id,
        runMode,
      });
      startTransition(() => {
        setLastRun(response);
        setLastRunMode(runMode);
        setLastSubmit(null);
        setExerciseActionState({ status: "idle" });
        setIsStale(false);
        setExplainErrorResult(null);
        setExplanationCheckResult(null);
        setExplanationRound(1);
        if (!response.idempotency_replayed && (response.runtime_status !== "success" || (runMode === "visible_tests" && response.test_pass_rate < 1))) {
          setErrorCount((current) => current + 1);
        }
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  async function handleSubmitExercise() {
    if (
      !session ||
      !activeExercise ||
      !lastRun ||
      isStale ||
      lastRun.runtime_status === "unsupported" ||
      lastRunMode !== "visible_tests"
    ) {
      return;
    }
    setLastExerciseAction("submit");
    const materializedCode = materializeExerciseCode(editorCode, filledBlanks);
    setExerciseActionState({ status: "loading", label: "正在提交结果并写回知识点状态" });
    try {
      const response = await submitLearningExercise({
        sessionId: session.session_id,
        exerciseId: activeExercise.id,
        attemptId: lastRun.attempt_id,
        code: materializedCode,
        filledBlanks,
        submitVersion: 1,
        explanation: explanationText.trim() || undefined,
        hintUsageCount,
        errorCount,
      });
      startTransition(() => {
        setLastSubmit(response);
        setExerciseActionState({ status: "idle" });
        setCreatedPlan((current) => (current ? applyKnowledgePointUpdate(current, response.KnowledgePoint) : current));
        setSessionState((current) =>
          current.status === "ready"
            ? {
                status: "ready",
                data: {
                  ...current.data,
                  context_snapshot: {
                    ...current.data.context_snapshot,
                    KnowledgePoint: {
                      ...current.data.context_snapshot.KnowledgePoint,
                      status: response.KnowledgePoint.status,
                    },
                  },
                },
              }
            : current,
        );
        setIsStale(false);
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  async function handleRequestHint() {
    if (!session || !activeExercise || !lastRun || isStale || !selectedBlankId) {
      return;
    }
    setLastExerciseAction("hint");
    setExerciseActionState({ status: "loading", label: "正在生成分层提示" });
    try {
      const response = await requestLearningHint({
        sessionId: session.session_id,
        exerciseId: activeExercise.id,
        attemptId: lastRun.attempt_id,
        currentCode: materializeExerciseCode(editorCode, filledBlanks),
        blankId: selectedBlankId,
        hintLevel,
      });
      startTransition(() => {
        setHintUsageCount((current) => Math.max(current, response.hint_usage_count));
        setHintHistory((current) => [response, ...current.filter((item) => item.hint.content !== response.hint.content)].slice(0, 4));
        setExerciseActionState({ status: "idle" });
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  async function handleExplainError() {
    if (!session || !lastRun || isStale) {
      return;
    }
    const failedTests = lastRun.test_results
      .filter((item) => !item.passed)
      .map((item) => ({
        case_id: item.case_id,
        case_type: item.case_type,
        message: item.message,
      }));
    if (lastRun.runtime_status === "success" && failedTests.length === 0) {
      return;
    }
    setLastExerciseAction("explain_error");
    setExerciseActionState({ status: "loading", label: "正在解释真实错误上下文" });
    try {
      const response = await explainLearningError({
        sessionId: session.session_id,
        attemptId: lastRun.attempt_id,
        errorMessage: lastRun.error_message,
        stderr: lastRun.stderr,
        failedTests,
        currentCode: materializeExerciseCode(editorCode, filledBlanks),
      });
      startTransition(() => {
        setExplainErrorResult(response);
        setExerciseActionState({ status: "idle" });
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  async function handleCheckExplanation() {
    if (!session || !lastRun || isStale || explanationText.trim().length === 0) {
      return;
    }
    setLastExerciseAction("check_explanation");
    setExerciseActionState({ status: "loading", label: "正在检查你对关键代码的解释" });
    try {
      const response = await checkLearningExplanation({
        sessionId: session.session_id,
        attemptId: lastRun.attempt_id,
        explanation: explanationText.trim(),
        focus: explanationFocus,
        round: explanationRound,
      });
      startTransition(() => {
        setExplanationCheckResult(response);
        setExerciseActionState({ status: "idle" });
        if (response.follow_up_required) {
          setExplanationRound((current) => Math.min(current + 1, 2));
        }
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  function handleRetryExerciseAction() {
    if (lastExerciseAction === "run_preview") {
      void handleRunExercise("preview");
      return;
    }
    if (lastExerciseAction === "run_tests") {
      void handleRunExercise("visible_tests");
      return;
    }
    if (lastExerciseAction === "submit") {
      void handleSubmitExercise();
      return;
    }
    if (lastExerciseAction === "hint") {
      void handleRequestHint();
      return;
    }
    if (lastExerciseAction === "explain_error") {
      void handleExplainError();
      return;
    }
    if (lastExerciseAction === "check_explanation") {
      void handleCheckExplanation();
    }
  }

  function goToRoute(route: AppRoute) {
    setActiveRoute(route);
    closeDrawers();
  }

  function closeDrawers() {
    setNoteDrawerOpen(false);
    setPublishDrawerOpen(false);
  }

  function toggleSidebar() {
    setSidebarOpen((current) => !current);
  }

  function toggleGroup(group: NavGroupKey) {
    setOpenGroups((current) => ({ ...current, [group]: !current[group] }));
  }

  function resetGoal() {
    setPlanDraft(null);
    setCreatedPlan(null);
    setSessionState({ status: "idle" });
    setActionState({ status: "idle" });
    setExerciseActionState({ status: "idle" });
    setLastRun(null);
    setLastSubmit(null);
    setIsStale(false);
    setLastRunMode(null);
    setLastExerciseAction(null);
    setHintUsageCount(0);
    setErrorCount(0);
    setHintLevel("nudge");
    setSelectedBlankId("");
    setHintHistory([]);
    setExplainErrorResult(null);
    setExplanationText("");
    setExplanationFocus("core_logic");
    setExplanationRound(1);
    setExplanationCheckResult(null);
    setEditorCode("");
    setFilledBlanks({});
    setHomeConversation([]);
    setReviewConversation([]);
    setActiveRoute("onboarding");
    closeDrawers();
  }

  function handleComposerSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (composerInput.trim().length === 0) {
      return;
    }
    if (visibleRoute === "review") {
      setReviewConversation((current) => [
        ...current,
        createMessage("user", composerInput.trim()),
        createMessage("agent", "收到。先按准确性、因果链、例子质量和表达清晰度评分，再决定下一次 due_at。", "Agent"),
      ]);
    } else {
      setHomeConversation((current) => [
        ...current,
        createMessage("user", composerInput.trim()),
        createMessage("agent", "收到。先把失败用例和你刚修改的那一行对齐，再决定是重跑、提交，还是继续追问错因。", "Agent"),
      ]);
    }
    setComposerInput("");
  }

  async function handleCopyPublish() {
    try {
      await navigator.clipboard.writeText(publishEditor);
      setPublishState("已复制");
    } catch {
      setPublishState("复制不可用");
    }
  }

  function handleSaveAttempt() {
    setNoteContent((current) => mergeAttemptIntoNote(current, noteDrawerText));
    setNoteSaveState("已保存");
  }

  function handleOpenPublishDrawer() {
    setNoteDrawerOpen(false);
    setPublishDrawerOpen(true);
    const currentDraft = RETROSPECTIVE_DRAFTS[publishDraftType];
    setPublishState(currentDraft.label);
    setPublishEditor(currentDraft.text);
  }

  function handlePublishTypeChange(nextType: PublishKey) {
    setPublishDraftType(nextType);
    setPublishState(RETROSPECTIVE_DRAFTS[nextType].label);
    setPublishEditor(RETROSPECTIVE_DRAFTS[nextType].text);
  }

  useEffect(() => {
    const controller = new AbortController();
    void bootstrap(controller.signal);

    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (session && activeExercise) {
      setNoteContent(buildSessionNote(session, activeExercise));
      setNoteDrawerText(buildAttemptDraft(activeExercise, lastRun, lastSubmit));
      setNoteSaveState("已保存");
    }
  }, [session?.session_id, activeExercise?.id]);

  useEffect(() => {
    if (activeExercise) {
      setNoteDrawerText(buildAttemptDraft(activeExercise, lastRun, lastSubmit));
      setNoteSaveState("已保存");
    }
  }, [activeExercise?.id, lastRun?.attempt_id, lastSubmit?.attempt_id]);

  useEffect(() => {
    if (createdPlan && activeRoute === "onboarding") {
      setActiveRoute("home");
    }
  }, [createdPlan, activeRoute]);

  return (
    <main className="stage">
      <section className={sidebarOpen ? "desktop" : "desktop sidebar-collapsed"} aria-label="Claude 桌面端风格 Aearn 框架">
        <header className="app-menu" aria-label="桌面应用菜单栏">
          <div className="menu-left">
            <button
              className="sidebar-toggle"
              type="button"
              aria-label={sidebarOpen ? "折叠左侧栏" : "展开左侧栏"}
              aria-expanded={sidebarOpen}
              onClick={toggleSidebar}
            >
              <img src="/sidebar.png" alt="" />
            </button>
            <div className="app-title">AI Code Learning</div>
          </div>
          <div className="menu-right">
            <button className="menu-icon settings-top" type="button" aria-label="设置" onClick={() => goToRoute("settings")}>
              <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M12 15.4a3.4 3.4 0 1 0 0-6.8 3.4 3.4 0 0 0 0 6.8Z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                />
                <path
                  d="M19.3 13.5c.1-.5.1-1 .1-1.5s0-1-.1-1.5l2-1.5-2-3.5-2.4 1a7 7 0 0 0-2.6-1.5L14 2.4h-4L9.7 5a7 7 0 0 0-2.6 1.5l-2.4-1-2 3.5 2 1.5a8.6 8.6 0 0 0 0 3l-2 1.5 2 3.5 2.4-1a7 7 0 0 0 2.6 1.5l.3 2.6h4l.3-2.6a7 7 0 0 0 2.6-1.5l2.4 1 2-3.5-2-1.5Z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
            <div className="window-controls" aria-hidden="true">
              <span className="window-btn">−</span>
              <span className="window-btn">□</span>
              <span className="window-btn">×</span>
            </div>
          </div>
        </header>

        <aside className={visibleRoute === "settings" ? "sidebar no-context" : "sidebar"} aria-label="应用侧边栏">
          <div className="brand">
            <span className="mark">A</span>
            <span className="brand-name">AI Code Learning</span>
          </div>

          <button className="new-goal" type="button" onClick={resetGoal}>
            <span>新编程目标</span>
            <span>+</span>
          </button>

          <SidebarNav
            activeRoute={visibleRoute}
            createdPlan={createdPlan}
            activeKnowledgePointId={activeKnowledgePointId}
            openGroups={openGroups}
            onToggleGroup={toggleGroup}
            onRouteChange={goToRoute}
          />

          <SideContext
            route={visibleRoute}
            createdPlan={createdPlan}
            activeKnowledgePointId={activeKnowledgePointId}
            lastSubmit={lastSubmit}
            onSelectKnowledgePoint={(knowledgePointId) => {
              if (createdPlan) {
                void openLearningSession(createdPlan, knowledgePointId);
              }
            }}
          />

          <footer className="sidebar-footer">
            <div className="progress" aria-label={`总进度 ${Math.round(sidebarProgress * 100)}%`}>
              <span style={{ width: `${sidebarProgress * 100}%` }}></span>
            </div>
            <span>{sidebarHint}</span>
          </footer>
        </aside>

        <section className="main" aria-label="工作区">
          <header className="topbar">
            <div className="crumb">{crumb}</div>
            <ApiHealthChip apiHealth={apiHealth} />
          </header>

          <section className={screenClassName(visibleRoute === "onboarding")} aria-label="首次建档">
            <div className="split-workspace">
              <div className="split-pane">
                <section className="conversation onboarding-conversation" aria-label="建档对话">
                  <div className="thread">
                    <ThreadMessages messages={ONBOARDING_MESSAGES} />
                    {selectedCourse && (
                      <article className="message agent">
                        <div className="avatar">A</div>
                        <div className="bubble">
                          <div className="bubble-label">Agent</div>
                          <p>当前课程模板会以 {selectedCourse.title} 为主干，运行能力是 {runtimeLabel(selectedCourse.runtime_profile.runtime_tier)}。</p>
                        </div>
                      </article>
                    )}
                  </div>

                  <div className="onboarding-setup">
                    <label className="inline-field">
                      <span>显示名称</span>
                      <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={isBusy} />
                    </label>

                    <div className="mode-tabs" role="tablist" aria-label="Onboarding mode">
                      <button
                        className={mode === "goal_based" ? "active" : ""}
                        type="button"
                        aria-selected={mode === "goal_based"}
                        onClick={() => setMode("goal_based")}
                      >
                        目标驱动
                      </button>
                      <button
                        className={mode === "material_based" ? "active" : ""}
                        type="button"
                        aria-selected={mode === "material_based"}
                        onClick={() => setMode("material_based")}
                      >
                        资料驱动
                      </button>
                    </div>

                    <div className="course-selector" aria-label="课程选择">
                      {courses.map((course) => (
                        <button
                          className={course.id === selectedCourse?.id ? "course-option active" : "course-option"}
                          key={course.id}
                          type="button"
                          disabled={isBusy}
                          onClick={() => {
                            setSelectedCourseId(course.id);
                            setPlanDraft(null);
                          }}
                        >
                          <strong>{course.title}</strong>
                          <span>{runtimeLabel(course.runtime_profile.runtime_tier)}</span>
                        </button>
                      ))}
                    </div>

                    {mode === "material_based" && (
                      <label className="inline-field">
                        <span>资料标题</span>
                        <input value={materialTitle} onChange={(event) => setMaterialTitle(event.target.value)} disabled={isBusy} />
                      </label>
                    )}
                  </div>

                  <div className="composer onboarding-composer">
                    <textarea
                      aria-label="建档输入"
                      value={mode === "goal_based" ? goalText : materialContent}
                      placeholder={mode === "goal_based" ? "描述你要学会的代码任务和时间边界" : "粘贴你已有的笔记、代码片段或知识点列表"}
                      onChange={(event) => {
                        if (mode === "goal_based") {
                          setGoalText(event.target.value);
                        } else {
                          setMaterialContent(event.target.value);
                        }
                      }}
                      disabled={isBusy}
                    />
                    <button
                      className="btn primary"
                      type="button"
                      disabled={!canGenerate || isBusy}
                      onClick={() => void (planDraft ? handleConfirm() : handleGenerate())}
                    >
                      {actionState.status === "loading" ? "处理中" : planDraft ? "确认" : "生成草稿"}
                    </button>
                    <button
                      className="btn primary send-btn"
                      type="button"
                      aria-label={planDraft ? "确认建档结果" : "生成计划草稿"}
                      disabled={!canGenerate || isBusy}
                      onClick={() => void (planDraft ? handleConfirm() : handleGenerate())}
                    >
                      ↑
                    </button>
                  </div>
                </section>
              </div>

              <div className="split-divider" aria-hidden="true"></div>

              <div className="split-pane">
                <PlanDraftPanel
                  actionState={actionState}
                  planDraft={planDraft}
                  selectedCourse={selectedCourse}
                  isBusy={isBusy}
                  onConfirm={() => void handleConfirm()}
                />
              </div>
            </div>
          </section>

          <section className={screenClassName(visibleRoute === "home")} aria-label="学习页">
            <section className="conversation" aria-label="Agent 代码练习对话">
              <div className="thread">
                <div className="lesson-title">
                  <p>{session ? `当前只解决一个问题：${session.context_snapshot.KnowledgePoint.title}。先运行，再根据测试结果决定下一步。` : "今天只解决一个问题：状态变量应该放在哪里，测试为什么会失败。"}</p>
                </div>

                <ThreadMessages messages={homeMessages} />

                {sessionState.status === "loading" && <SystemCard title="系统状态" body="正在启动当前知识点会话…" />}
                {sessionState.status === "error" && (
                  <SystemCard
                    title="启动失败"
                    body={sessionState.message}
                    actionLabel="重试当前知识点"
                    onAction={() => {
                      if (createdPlan && sessionState.knowledgePointId) {
                        void openLearningSession(createdPlan, sessionState.knowledgePointId);
                      }
                    }}
                  />
                )}

                {!session && sessionState.status === "idle" && (
                  <SystemCard
                    title="会话未开始"
                    body="确认学习计划后，主页会在这里承载真实 M3 练习、运行反馈和提交结果。"
                  />
                )}

                {session && activeExercise && (
                  <>
                    <article className="message agent">
                      <div className="avatar">A</div>
                      <div className="bubble">
                        <div className="bubble-label">Agent</div>
                        <p>{session.initial_agent_message}</p>
                        <div className="tool-card">
                          当前练习：{activeExercise.title} · {session.context_snapshot.KnowledgePoint.title}
                        </div>
                      </div>
                    </article>

                    <ExerciseWorkbench
                      session={session}
                      exercise={activeExercise}
                      code={editorCode}
                      filledBlanks={filledBlanks}
                      lastRun={lastRun}
                      lastRunMode={lastRunMode}
                      lastSubmit={lastSubmit}
                      actionState={exerciseActionState}
                      isStale={isStale}
                      hintUsageCount={hintUsageCount}
                      errorCount={errorCount}
                      hintLevel={hintLevel}
                      selectedBlankId={selectedBlankId}
                      hintHistory={hintHistory}
                      explainErrorResult={explainErrorResult}
                      explanationText={explanationText}
                      explanationFocus={explanationFocus}
                      explanationRound={explanationRound}
                      explanationCheckResult={explanationCheckResult}
                      onCodeChange={(value) => {
                        setEditorCode(value);
                        if (lastRun || lastSubmit) {
                          setIsStale(true);
                        }
                      }}
                      onBlankChange={(blankKey, value) => {
                        setFilledBlanks((current) => ({ ...current, [blankKey]: value }));
                        if (lastRun || lastSubmit) {
                          setIsStale(true);
                        }
                      }}
                      onRunPreview={() => void handleRunExercise("preview")}
                      onRunVisibleTests={() => void handleRunExercise("visible_tests")}
                      onSubmit={() => void handleSubmitExercise()}
                      onHintLevelChange={setHintLevel}
                      onSelectedBlankChange={setSelectedBlankId}
                      onRequestHint={() => void handleRequestHint()}
                      onExplainError={() => void handleExplainError()}
                      onExplanationTextChange={setExplanationText}
                      onExplanationFocusChange={setExplanationFocus}
                      onCheckExplanation={() => void handleCheckExplanation()}
                      onRetryAction={() => handleRetryExerciseAction()}
                      onOpenPublishDrawer={handleOpenPublishDrawer}
                    />
                  </>
                )}
              </div>
            </section>
          </section>

          <section className={screenClassName(visibleRoute === "review")} aria-label="复习页">
            <div className="review-screen">
              <div className="review-thread-wrap">
                <section className="conversation" aria-label="复习新会话">
                  <div className="thread">
                    <div className="lesson-title">
                      <p>这是一个独立新会话，避免和当前代码练习互相干扰。输入栏保持与主页一致。</p>
                    </div>

                    <ThreadMessages messages={reviewMessages} />

                    {lastSubmit && (
                      <article className="message agent">
                        <div className="avatar">A</div>
                        <div className="bubble">
                          <div className="bubble-label">Agent</div>
                          <p>最近一次提交已经写回复习状态。下一轮会优先追打 {lastSubmit.code_completion_result.weak_points[0] ?? "状态变量生命周期"}。</p>
                          <div className="tool-card">
                            FSRS：{lastSubmit.code_completion_result.fsrs_rating} · 下一步：{lastSubmit.next_action}
                          </div>
                        </div>
                      </article>
                    )}

                    <ReviewRecap lastSubmit={lastSubmit} lastRun={lastRun} />
                  </div>
                </section>
              </div>
            </div>
          </section>

          <section className={screenClassName(visibleRoute === "notes")} aria-label="笔记页">
            <div className="notes-layout">
              <section className="note-editor-panel" aria-label="Markdown 笔记书写区域">
                <textarea
                  className="note-content-editor"
                  aria-label="Markdown 笔记书写区域"
                  value={noteContent}
                  onChange={(event) => setNoteContent(event.target.value)}
                />
              </section>
            </div>
          </section>

          <section className={screenClassName(visibleRoute === "settings")} aria-label="设置页">
            <div className="settings-screen">
              <div className="kicker">Settings</div>
              <p>横向列表包含外观、模型设置、通知设置、Attempt 记录配置、练习设置和关于。</p>

              <div className="settings-tabs" role="tablist" aria-label="设置分类">
                {Object.entries(SETTING_PANELS).map(([key, panel]) => (
                  <button
                    className={settingsTab === key ? "settings-tab active" : "settings-tab"}
                    key={key}
                    type="button"
                    onClick={() => setSettingsTab(key as SettingsKey)}
                  >
                    {panel.title}
                  </button>
                ))}
              </div>

              <div className="settings-content">
                <section className="panel pad stack">
                  <div className="panel-head">
                    <div>
                      <h2>{currentSettingsPanel.title}</h2>
                      <span className="meta">{currentSettingsPanel.meta}</span>
                    </div>
                    <button className="btn primary" type="button">
                      保存设置
                    </button>
                  </div>
                  <div className="settings-grid">
                    {currentSettingsPanel.cards.map(([title, body]) => (
                      <article className="setting-card" key={`${settingsTab}-${title}`}>
                        <h3>{title}</h3>
                        <p>{body}</p>
                      </article>
                    ))}
                  </div>
                </section>

                <aside className="panel pad stack">
                  <h2>当前配置摘要</h2>
                  <div className="settings-mini active">
                    <h3 className="mini-title">提示策略</h3>
                    <p className="mini-body">先 hint 后解释，必要时再给最小代码片段。</p>
                  </div>
                  <div className="settings-mini">
                    <h3 className="mini-title">提醒策略</h3>
                    <p className="mini-body">due_at 到期时，优先进入复习页。</p>
                  </div>
                  <div className="settings-mini">
                    <h3 className="mini-title">代码控制权</h3>
                    <p className="mini-body">Agent 可解释错因，但用户保留最终补全权。</p>
                  </div>
                </aside>
              </div>
            </div>
          </section>

          <div className={noteDrawerOpen || publishDrawerOpen ? "drawer-scrim open" : "drawer-scrim"} onClick={closeDrawers}></div>

          <section className={noteDrawerOpen ? "drawer open" : "drawer"} aria-label="尝试记录弹窗" aria-hidden={!noteDrawerOpen}>
            <div className="drawer-head">
              <h2>尝试记录</h2>
              <div className="note-status">
                <span>{noteSaveState}</span>
                <button className="icon-btn" type="button" aria-label="保存尝试记录" onClick={handleSaveAttempt}>
                  ✓
                </button>
              </div>
            </div>
            <textarea
              className="drawer-editor"
              aria-label="尝试记录编辑器"
              value={noteDrawerText}
              onChange={(event) => {
                setNoteDrawerText(event.target.value);
                setNoteSaveState("未保存");
              }}
            />
          </section>

          <section className={publishDrawerOpen ? "drawer open" : "drawer"} aria-label="复盘草稿弹窗" aria-hidden={!publishDrawerOpen}>
            <div className="drawer-head">
              <h2>复盘草稿</h2>
              <div className="note-status">
                <span>{publishState}</span>
                <button className="icon-btn" type="button" aria-label="复制复盘草稿" onClick={() => void handleCopyPublish()}>
                  ⧉
                </button>
              </div>
            </div>
            <div className="publish-draft">
              <div className="platform-row" aria-label="草稿类型">
                {Object.entries(RETROSPECTIVE_DRAFTS).map(([key, draft]) => (
                  <button
                    className={publishDraftType === key ? "platform-btn active" : "platform-btn"}
                    key={key}
                    type="button"
                    onClick={() => handlePublishTypeChange(key as PublishKey)}
                  >
                    {draft.label.replace("格式", "")}
                  </button>
                ))}
              </div>
              <textarea
                className="drawer-editor"
                aria-label="复盘草稿内容"
                value={publishEditor}
                onChange={(event) => setPublishEditor(event.target.value)}
              />
            </div>
          </section>

          {(visibleRoute === "home" || visibleRoute === "review") && (
            <form className="composer-wrap" onSubmit={handleComposerSubmit}>
              <div className="composer">
                <textarea
                  aria-label="代码练习输入框"
                  value={composerInput}
                  placeholder={visibleRoute === "review" ? "用自己的话复述，或请求提示……" : "粘贴你的代码、运行输出、测试失败或请 Agent 解释错因……"}
                  onChange={(event) => setComposerInput(event.target.value)}
                />
                <button
                  className="btn primary send-btn note-inline-btn"
                  type="button"
                  aria-label={noteDrawerOpen ? "关闭尝试记录" : "打开尝试记录"}
                  aria-controls="noteDrawer"
                  aria-expanded={noteDrawerOpen}
                  onClick={() => {
                    setPublishDrawerOpen(false);
                    setNoteDrawerOpen((current) => !current);
                  }}
                >
                  <img src="/note.png" alt="" />
                </button>
                <button className="btn primary send-btn" type="submit" aria-label="发送">
                  ↑
                </button>
              </div>
            </form>
          )}
        </section>
      </section>
    </main>
  );
}

function SidebarNav({
  activeRoute,
  createdPlan,
  activeKnowledgePointId,
  openGroups,
  onToggleGroup,
  onRouteChange,
}: {
  activeRoute: AppRoute;
  createdPlan: CreatedPlanResponse | null;
  activeKnowledgePointId: string;
  openGroups: Record<NavGroupKey, boolean>;
  onToggleGroup: (group: NavGroupKey) => void;
  onRouteChange: (route: AppRoute) => void;
}) {
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

function NestedNotesGroup({
  groupKey,
  title,
  items,
  activeRoute,
  isOpen,
  onToggle,
  onRouteChange,
}: {
  groupKey: NavGroupKey;
  title: string;
  items: string[];
  activeRoute: AppRoute;
  isOpen: boolean;
  onToggle: (group: NavGroupKey) => void;
  onRouteChange: (route: AppRoute) => void;
}) {
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

function SideContext({
  route,
  createdPlan,
  activeKnowledgePointId,
  lastSubmit,
  onSelectKnowledgePoint,
}: {
  route: AppRoute;
  createdPlan: CreatedPlanResponse | null;
  activeKnowledgePointId: string;
  lastSubmit: SubmitExerciseResponse | null;
  onSelectKnowledgePoint: (knowledgePointId: string) => void;
}) {
  if (route === "settings") {
    return null;
  }

  if (route === "onboarding") {
    return (
      <section className="side-context" aria-live="polite">
        <h2>模型思考与工具调用</h2>
        <div className="context-stack">
          <article className="trace-card">
            <span className="trace-dot"></span>
            <div>
              <h3 className="trace-title">analyze_goal</h3>
              <p className="trace-body">识别用户目标：JavaScript/HTML/CSS、Python、AI 生成代码理解、测试验证。</p>
            </div>
          </article>
          <article className="trace-card">
            <span className="trace-dot"></span>
            <div>
              <h3 className="trace-title">ask_clarifying_question</h3>
              <p className="trace-body">继续追问当前水平、目标用途、运行环境和时间边界。</p>
            </div>
          </article>
          <article className="trace-card">
            <span className="trace-dot"></span>
            <div>
              <h3 className="trace-title">generate_course_draft</h3>
              <p className="trace-body">根据语言目标生成五段编程课程草稿。</p>
            </div>
          </article>
        </div>
      </section>
    );
  }

  if (route === "review") {
    const reviewCards = buildReviewCards(lastSubmit);
    return (
      <section className="side-context" aria-live="polite">
        <h2>复习概览</h2>
        <div className="context-stack">
          {reviewCards.map((card, index) => (
            <article className={index === 0 ? "review-mini active" : "review-mini"} key={card.title}>
              <h3 className="mini-title">{card.title}</h3>
              <p className="mini-body">{card.body}</p>
            </article>
          ))}
        </div>
      </section>
    );
  }

  const routeCards = buildRouteCards(createdPlan, activeKnowledgePointId);
  return (
    <section className="side-context" aria-live="polite">
      <h2>编程路线</h2>
      <div className="context-stack">
        {routeCards.map((card) => (
          <button
            className={card.active ? "route-card route-card-button active" : "route-card route-card-button"}
            key={card.id}
            type="button"
            disabled={!card.knowledgePointId}
            onClick={() => {
              if (card.knowledgePointId) {
                onSelectKnowledgePoint(card.knowledgePointId);
              }
            }}
          >
            <span className="route-index">{card.index}</span>
            <div>
              <h3 className="mini-title">{card.title}</h3>
              <p className="mini-body">{card.body}</p>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

function PlanDraftPanel({
  actionState,
  planDraft,
  selectedCourse,
  isBusy,
  onConfirm,
}: {
  actionState: AsyncActionState;
  planDraft: PlanDraft | null;
  selectedCourse: LanguageCourse | null;
  isBusy: boolean;
  onConfirm: () => void;
}) {
  const modules = planDraft ? planDraft.modules.map(mapDraftModuleCard) : buildFallbackDraftModules();

  return (
    <div className="stack">
      <div>
        <div className="kicker">Live Plan Draft</div>
        <p>右侧只展示草稿。确认后才会写入正式练习计划，并在主页开始执行。</p>
      </div>

      {selectedCourse && (
        <div className="draft-summary">
          <strong>{selectedCourse.title}</strong>
          <span>{runtimeLabel(selectedCourse.runtime_profile.runtime_tier)}</span>
        </div>
      )}

      {actionState.status === "loading" && <div className="tool-card">{actionState.label}</div>}
      {actionState.status === "error" && (
        <article className="review-mini active error-card">
          <h3 className="mini-title">
            {actionState.code} {actionState.recoverable ? "可重试" : "需修复"}
          </h3>
          <p className="mini-body">{actionState.message}</p>
        </article>
      )}

      <div className="draft-route">
        {modules.map((module, index) => (
          <article className={index === 0 ? "draft-module active" : "draft-module"} key={module.id}>
            <span className="module-index">{index + 1}</span>
            <div>
              <h3>{module.title}</h3>
              <span className="meta">{module.description}</span>
            </div>
            <span className={module.tagClass}>{module.tag}</span>
          </article>
        ))}
      </div>

      {planDraft && (
        <>
          <div className="draft-boundary">{planDraft.runtime_boundary.notice}</div>
          <div className="source-strip">
            {planDraft.source_attribution.map((source) => (
              <span key={source}>{source}</span>
            ))}
          </div>
          <button className="btn primary confirm-draft-btn" type="button" disabled={isBusy} onClick={onConfirm}>
            确认学习计划并进入会话
          </button>
        </>
      )}
    </div>
  );
}

function ExerciseWorkbench({
  session,
  exercise,
  code,
  filledBlanks,
  lastRun,
  lastRunMode,
  lastSubmit,
  actionState,
  isStale,
  hintUsageCount,
  errorCount,
  hintLevel,
  selectedBlankId,
  hintHistory,
  explainErrorResult,
  explanationText,
  explanationFocus,
  explanationRound,
  explanationCheckResult,
  onCodeChange,
  onBlankChange,
  onRunPreview,
  onRunVisibleTests,
  onSubmit,
  onHintLevelChange,
  onSelectedBlankChange,
  onRequestHint,
  onExplainError,
  onExplanationTextChange,
  onExplanationFocusChange,
  onCheckExplanation,
  onRetryAction,
  onOpenPublishDrawer,
}: {
  session: LearningSessionResponse;
  exercise: LearningExercise;
  code: string;
  filledBlanks: Record<string, string>;
  lastRun: RunExerciseResponse | null;
  lastRunMode: "preview" | "visible_tests" | null;
  lastSubmit: SubmitExerciseResponse | null;
  actionState: AsyncActionState;
  isStale: boolean;
  hintUsageCount: number;
  errorCount: number;
  hintLevel: HintLevel;
  selectedBlankId: string;
  hintHistory: HintResponse[];
  explainErrorResult: ExplainErrorResponse | null;
  explanationText: string;
  explanationFocus: ExplanationFocus;
  explanationRound: number;
  explanationCheckResult: ExplanationCheckResponse | null;
  onCodeChange: (value: string) => void;
  onBlankChange: (blankKey: string, value: string) => void;
  onRunPreview: () => void;
  onRunVisibleTests: () => void;
  onSubmit: () => void;
  onHintLevelChange: (value: HintLevel) => void;
  onSelectedBlankChange: (value: string) => void;
  onRequestHint: () => void;
  onExplainError: () => void;
  onExplanationTextChange: (value: string) => void;
  onExplanationFocusChange: (value: ExplanationFocus) => void;
  onCheckExplanation: () => void;
  onRetryAction: () => void;
  onOpenPublishDrawer: () => void;
}) {
  const runtimeUnsupported = exercise.runtime_profile.runtime_tier === "compiled_sandbox_later";
  const hasFailedRun = lastRun !== null && (lastRun.runtime_status !== "success" || lastRun.test_results.some((item) => !item.passed));
  const submitDisabled =
    runtimeUnsupported ||
    lastRun === null ||
    lastRunMode !== "visible_tests" ||
    isStale ||
    lastRun.runtime_status === "unsupported";
  const hintDisabled = runtimeUnsupported || lastRun === null || isStale || selectedBlankId.length === 0;
  const explainDisabled = runtimeUnsupported || lastRun === null || isStale || !hasFailedRun;
  const checkDisabled = runtimeUnsupported || lastRun === null || isStale || explanationText.trim().length === 0;
  const workbenchState = runtimeUnsupported
    ? "unsupported"
    : actionState.status === "loading"
      ? "running"
      : lastSubmit
        ? "submitted"
        : isStale
          ? "dirty"
          : "pristine";
  const actionError = actionState.status === "error" ? actionState : null;

  return (
    <section className="exercise-workbench">
      <div className="exercise-head">
        <div>
          <div className="kicker">Runtime Slice</div>
          <h2>{exercise.title}</h2>
        </div>
        <div className="workbench-head-meta">
          <span className="runtime-pill">{runtimeLabel(exercise.runtime_profile.runtime_tier)}</span>
          <span className={`editor-state editor-state-${workbenchState}`}>{workbenchStateLabel(workbenchState)}</span>
        </div>
      </div>

      <div className="thread-meta">
        <span>阶段：{session.context_snapshot.current_stage}</span>
        <span>知识点：{session.context_snapshot.KnowledgePoint.title}</span>
        <span>题型：{exercise.exercise_type}</span>
        <span>提示 {hintUsageCount} 次</span>
        <span>错误 {errorCount} 次</span>
      </div>

      <div className="exercise-grid">
        <article className="panel pad stack exercise-panel">
          <div className="tool-card">题面：{exercise.prompt_markdown}</div>

          {exercise.code_blanks.length > 0 && (
            <div className="blank-grid">
              {exercise.code_blanks.map((blank) => (
                <label className="blank-card" key={blank.id}>
                  <span>{blank.blank_key}</span>
                  <strong>{blank.expected_concept}</strong>
                  <input
                    value={filledBlanks[blank.blank_key] ?? ""}
                    placeholder={blank.placeholder}
                    onChange={(event) => onBlankChange(blank.blank_key, event.target.value)}
                    disabled={actionState.status === "loading"}
                  />
                </label>
              ))}
            </div>
          )}

          <label className="exercise-editor">
            <span>代码区</span>
            <textarea className="drawer-editor code-editor" value={code} onChange={(event) => onCodeChange(event.target.value)} />
          </label>
          <p className="meta">运行和提交前会自动把 `__BLANK_x__` 占位符替换成上方空缺输入。</p>

          {runtimeUnsupported && (
            <div className="draft-boundary">当前课程属于 compiled_sandbox_later。本切片只展示静态补全，不开放完整编译运行与最终提交评分。</div>
          )}
        </article>

        <article className="panel pad stack exercise-panel">
          <div className="action-row action-row-wrap">
            {exercise.runtime_profile.runtime_tier === "browser_preview" && (
              <button
                className="btn primary"
                type="button"
                disabled={runtimeUnsupported || actionState.status === "loading"}
                onClick={onRunPreview}
              >
                运行预览
              </button>
            )}
            <button
              className="btn primary"
              type="button"
              disabled={runtimeUnsupported || actionState.status === "loading"}
              onClick={onRunVisibleTests}
            >
              运行可见测试
            </button>
            <button className="btn primary ghost-btn" type="button" disabled={submitDisabled || actionState.status === "loading"} onClick={onSubmit}>
              提交结果
            </button>
            <button className="btn primary ghost-btn" type="button" onClick={onOpenPublishDrawer}>
              复盘草稿
            </button>
          </div>

          <div className="action-row action-row-wrap assist-row">
            <label className="inline-select">
              <span>提示目标</span>
              <select
                value={selectedBlankId}
                disabled={hintDisabled || actionState.status === "loading"}
                onChange={(event) => onSelectedBlankChange(event.target.value)}
              >
                {exercise.code_blanks.map((blank) => (
                  <option key={blank.id} value={blank.blank_key}>
                    {blank.blank_key}
                  </option>
                ))}
              </select>
            </label>
            <label className="inline-select">
              <span>提示层级</span>
              <select value={hintLevel} disabled={hintDisabled || actionState.status === "loading"} onChange={(event) => onHintLevelChange(event.target.value as HintLevel)}>
                <option value="nudge">nudge</option>
                <option value="concept">concept</option>
                <option value="code_shape">code_shape</option>
              </select>
            </label>
            <button className="btn primary ghost-btn" type="button" disabled={hintDisabled || actionState.status === "loading"} onClick={onRequestHint}>
              获取提示
            </button>
            <button className="btn primary ghost-btn" type="button" disabled={explainDisabled || actionState.status === "loading"} onClick={onExplainError}>
              解释错误
            </button>
          </div>

          <label className="exercise-editor explanation-editor">
            <span>解释关键代码</span>
            <textarea
              className="drawer-editor explanation-textarea"
              value={explanationText}
              placeholder="用自己的话解释关键代码、边界条件，或为什么这次修改能修复错误。"
              onChange={(event) => onExplanationTextChange(event.target.value)}
            />
          </label>

          <div className="action-row action-row-wrap">
            <label className="inline-select">
              <span>检查焦点</span>
              <select value={explanationFocus} disabled={runtimeUnsupported || actionState.status === "loading"} onChange={(event) => onExplanationFocusChange(event.target.value as ExplanationFocus)}>
                <option value="core_logic">core_logic</option>
                <option value="boundary_condition">boundary_condition</option>
                <option value="ai_generated_change">ai_generated_change</option>
              </select>
            </label>
            <div className="tool-chip">当前轮次 {explanationRound} / 2</div>
            <button className="btn primary ghost-btn" type="button" disabled={checkDisabled || actionState.status === "loading"} onClick={onCheckExplanation}>
              检查解释
            </button>
          </div>

          {actionState.status === "loading" && <div className="tool-card">{actionState.label}</div>}
          {actionError && (
            <div className="draft-boundary action-error">
              <div>
                {actionError.code}: {actionError.message}
              </div>
              {actionError.recoverable && (
                <button className="btn primary ghost-btn" type="button" onClick={onRetryAction}>
                  重试上一步
                </button>
              )}
            </div>
          )}
          {isStale && lastRun && <div className="draft-boundary">你已经修改了代码，下面的结果来自上一次运行，请先重新运行。</div>}
          {submitDisabled && lastRunMode === "preview" && <div className="draft-boundary">提交前需要先跑一次“运行可见测试”，预览结果不会直接进入评分。</div>}
          {submitDisabled && !lastRun && <div className="draft-boundary">先运行一次，拿到当前 Attempt 后才能提交评分、获取提示或检查解释。</div>}

          {!lastRun && !lastSubmit && <div className="empty-block">先运行一次，右侧会出现预览、stdout、测试结果和提交摘要。</div>}

          {hintHistory.length > 0 && <HintHistoryCard items={hintHistory} />}
          {explainErrorResult && <ErrorFeedbackPane result={explainErrorResult} />}
          {explanationCheckResult && <ExplanationCheckPanel result={explanationCheckResult} />}
          {lastRun && <RuntimeFeedback result={lastRun} runMode={lastRunMode} />}
          {lastSubmit && <SubmissionSummary result={lastSubmit} />}
        </article>
      </div>
    </section>
  );
}

function RuntimeFeedback({
  result,
  runMode,
}: {
  result: RunExerciseResponse;
  runMode: "preview" | "visible_tests" | null;
}) {
  return (
    <div className="runtime-feedback-grid">
      {result.preview_html && (
        <article className="result-card">
          <div className="panel-head">
            <h3>浏览器预览</h3>
            <span>{runMode === "preview" ? "preview" : `${Math.round(result.test_pass_rate * 100)}%`}</span>
          </div>
          <iframe className="preview-frame" srcDoc={result.preview_html} title="exercise-preview" />
        </article>
      )}

      <article className="result-card">
        <div className="panel-head">
          <h3>{runMode === "preview" ? "运行反馈" : "测试与运行反馈"}</h3>
          <span>{runtimeStatusLabel(result.runtime_status)}</span>
        </div>
        <p className="meta">
          通过 {result.passed_test_count} / {result.total_test_count} · 下一步 {nextActionLabel(result.next_action)}
        </p>
        {result.stdout && (
          <div className="output-block">
            <strong>stdout</strong>
            <pre>{result.stdout}</pre>
          </div>
        )}
        {result.stderr && (
          <div className="output-block">
            <strong>stderr</strong>
            <pre>{result.stderr}</pre>
          </div>
        )}
        {result.error_message && <p className="mini-body">{result.error_message}</p>}
        <ul className="test-result-list">
          {result.test_results.map((item) => (
            <li className={item.passed ? "passed" : "failed"} key={item.case_id}>
              <strong>{item.case_type}</strong>
              <span>{item.message}</span>
            </li>
          ))}
        </ul>
      </article>
    </div>
  );
}

function HintHistoryCard({ items }: { items: HintResponse[] }) {
  return (
    <article className="result-card hint-history-card">
      <div className="panel-head">
        <h3>提示历史</h3>
        <span>{items[0]?.hint_usage_count ?? 0} 次</span>
      </div>
      <ul className="hint-history-list">
        {items.map((item, index) => (
          <li key={`${item.hint.hint_level}-${index}`}>
            <strong>{item.hint.hint_level}</strong>
            <p>{item.hint.content}</p>
          </li>
        ))}
      </ul>
    </article>
  );
}

function ErrorFeedbackPane({ result }: { result: ExplainErrorResponse }) {
  return (
    <article className="result-card error-feedback-card">
      <div className="panel-head">
        <h3>错因解释</h3>
        <span>{result.error_cause}</span>
      </div>
      <p>{result.explanation}</p>
      <div className="output-block">
        <strong>修正建议</strong>
        <p>{result.fix_suggestion}</p>
      </div>
      {result.related_knowledge_points.length > 0 && (
        <div className="related-kp-strip">
          {result.related_knowledge_points.map((item) => (
            <span key={item.id}>{item.title}</span>
          ))}
        </div>
      )}
    </article>
  );
}

function ExplanationCheckPanel({ result }: { result: ExplanationCheckResponse }) {
  return (
    <article className="result-card explanation-check-card">
      <div className="panel-head">
        <h3>解释检查</h3>
        <span>{result.result}</span>
      </div>
      <p>{result.feedback}</p>
      <div className="metric-grid compact-metric-grid">
        <div>
          <span>得分</span>
          <strong>{result.score} / 2</strong>
        </div>
        <div>
          <span>后续动作</span>
          <strong>{nextActionLabel(result.next_action)}</strong>
        </div>
        <div>
          <span>需要追问</span>
          <strong>{result.follow_up_required ? "是" : "否"}</strong>
        </div>
      </div>
    </article>
  );
}

function SubmissionSummary({ result }: { result: SubmitExerciseResponse }) {
  return (
    <article className="submit-summary">
      <div className="panel-head">
        <div>
          <div className="kicker">Submit Result</div>
          <h3>提交摘要</h3>
        </div>
        <span className="result-pill">{result.code_completion_result.result}</span>
      </div>

      <p>{result.code_completion_result.feedback}</p>

      <div className="metric-grid">
        <div>
          <span>总分</span>
          <strong>{result.code_completion_result.score} / 8</strong>
        </div>
        <div>
          <span>FSRS Rating</span>
          <strong>{result.code_completion_result.fsrs_rating}</strong>
        </div>
        <div>
          <span>下一步</span>
          <strong>{result.next_action}</strong>
        </div>
      </div>

      <div className="gate-grid">
        {Object.entries(result.code_completion_result.hard_gates).map(([gate, passed]) => (
          <div className={passed ? "gate-pass" : "gate-fail"} key={gate}>
            <span>{gate}</span>
            <strong>{passed ? "pass" : "fail"}</strong>
          </div>
        ))}
      </div>

      {result.code_completion_result.weak_points.length > 0 && (
        <ul className="weak-point-list">
          {result.code_completion_result.weak_points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      )}
    </article>
  );
}

function ReviewRecap({
  lastSubmit,
  lastRun,
}: {
  lastSubmit: SubmitExerciseResponse | null;
  lastRun: RunExerciseResponse | null;
}) {
  const cards = buildReviewCards(lastSubmit, lastRun);
  return (
    <div className="review-recap-grid">
      {cards.map((card, index) => (
        <article className={index === 0 ? "review-card active" : "review-card"} key={card.title}>
          <h3>{card.title}</h3>
          <p>{card.body}</p>
        </article>
      ))}
    </div>
  );
}

function ThreadMessages({ messages }: { messages: ConversationMessage[] }) {
  return (
    <>
      {messages.map((message) => (
        <article className={`message ${message.speaker}`} key={message.id}>
          <div className="avatar">{message.speaker === "agent" ? "A" : "你"}</div>
          <div className="bubble">
            {message.label && <div className="bubble-label">{message.label}</div>}
            {renderMessageBody(message.text)}
            {message.toolCard && <div className="tool-card">{message.toolCard}</div>}
          </div>
        </article>
      ))}
    </>
  );
}

function SystemCard({
  title,
  body,
  actionLabel,
  onAction,
}: {
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <article className="system-card">
      <h3>{title}</h3>
      <p>{body}</p>
      {actionLabel && onAction && (
        <button className="btn primary ghost-btn" type="button" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </article>
  );
}

function ApiHealthChip({ apiHealth }: { apiHealth: ApiHealthState }) {
  if (apiHealth.status === "loading") {
    return <div className="status-chip">API 检测中</div>;
  }
  if (apiHealth.status === "offline") {
    return <div className="status-chip offline">API 离线 · {apiHealth.message}</div>;
  }
  return <div className="status-chip online">{apiHealth.data.service} 在线</div>;
}

function renderMessageBody(text: string) {
  return text.split("\n").map((line, index) => <p key={`${text}-${index}`}>{line}</p>);
}

function screenClassName(active: boolean): string {
  return active ? "screen active" : "screen";
}

function getCrumbLabel(
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

function buildLearnNavItems(plan: CreatedPlanResponse | null, activeKnowledgePointId: string) {
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

function buildRouteCards(plan: CreatedPlanResponse | null, activeKnowledgePointId: string) {
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

function buildReviewCards(lastSubmit: SubmitExerciseResponse | null, lastRun?: RunExerciseResponse | null) {
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

function buildFallbackDraftModules() {
  return [
    { id: "draft-1", title: "HTML 结构与 CSS 选择器", description: "建立页面结构、选择器和实时预览的共同语言", tag: "保留", tagClass: "tag strong" },
    { id: "draft-2", title: "JavaScript DOM 事件", description: "理解事件监听、状态变量和输出更新", tag: "主干", tagClass: "tag warn" },
    { id: "draft-3", title: "Python 函数与测试", description: "将补全结果与断言、测试反馈连接", tag: "新增", tagClass: "tag" },
    { id: "draft-4", title: "AI 生成代码理解", description: "识别关键路径、冗余代码和可验证修改", tag: "可压缩", tagClass: "tag" },
    { id: "draft-5", title: "调试一个小型页面", description: "用完整练习完成运行、测试和复盘", tag: "终局", tagClass: "tag" },
  ];
}

function mapDraftModuleCard(module: PlanDraft["modules"][number]) {
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

function buildSessionNote(session: LearningSessionResponse, exercise: LearningExercise): string {
  return `# ${exercise.title}

知识点：${session.context_snapshot.KnowledgePoint.title}
运行能力：${runtimeLabel(exercise.runtime_profile.runtime_tier)}

题面：
${exercise.prompt_markdown}

Attempt 记录：
- 先运行最小修改，再根据可见测试决定是否提交。
- 如果失败，记录错因、修改位置和下一步问题。`;
}

function buildAttemptDraft(
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

function mergeAttemptIntoNote(currentNote: string, attempt: string): string {
  if (currentNote.includes(attempt.trim())) {
    return currentNote;
  }
  return `${currentNote.trim()}\n\n${attempt.trim()}`;
}

function createMessage(speaker: ConversationMessage["speaker"], text: string, label?: string): ConversationMessage {
  messageCounter += 1;
  return {
    id: `msg-${messageCounter}`,
    speaker,
    text,
    label,
  };
}

function computeSidebarProgress(plan: CreatedPlanResponse): number {
  if (plan.knowledge_points.length === 0) {
    return 0;
  }
  const progressed = plan.knowledge_points.filter((item) => item.status !== "pending").length;
  return progressed / plan.knowledge_points.length;
}

function runtimeLabel(runtimeTier: string): string {
  if (runtimeTier === "browser_preview") {
    return "浏览器预览 + DOM 断言";
  }
  if (runtimeTier === "python_stdout_test") {
    return "Python stdout + 可见测试";
  }
  return "编译沙箱后置";
}

function runtimeStatusLabel(runtimeStatus: string): string {
  if (runtimeStatus === "runtime_error") {
    return "运行错误";
  }
  if (runtimeStatus === "timeout") {
    return "执行超时";
  }
  if (runtimeStatus === "unsupported") {
    return "能力未开放";
  }
  return "运行成功";
}

function nextActionLabel(nextAction: string): string {
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

function workbenchStateLabel(state: "pristine" | "dirty" | "running" | "submitted" | "unsupported"): string {
  if (state === "dirty") {
    return "dirty";
  }
  if (state === "running") {
    return "running";
  }
  if (state === "submitted") {
    return "submitted";
  }
  if (state === "unsupported") {
    return "unsupported";
  }
  return "pristine";
}

function knowledgePointStatusLabel(status: CreatedKnowledgePoint["status"]): string {
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

function initialBlankState(exercise: LearningExercise): Record<string, string> {
  return Object.fromEntries(exercise.code_blanks.map((blank) => [blank.blank_key, ""]));
}

function materializeExerciseCode(code: string, filledBlanks: Record<string, string>): string {
  return Object.entries(filledBlanks).reduce((currentCode, [blankKey, value]) => {
    const token = `__${blankKey.toUpperCase()}__`;
    return currentCode.replaceAll(token, value.trim() || token);
  }, code);
}

function markKnowledgePointLearning(plan: CreatedPlanResponse, knowledgePointId: string): CreatedPlanResponse {
  return {
    ...plan,
    knowledge_points: plan.knowledge_points.map((knowledgePoint) =>
      knowledgePoint.id === knowledgePointId ? { ...knowledgePoint, status: "learning" } : knowledgePoint,
    ),
  };
}

function applyKnowledgePointUpdate(
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

function toActionError(error: unknown): AsyncActionState {
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

export default App;
