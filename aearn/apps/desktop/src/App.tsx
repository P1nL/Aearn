import { startTransition, useDeferredValue, useEffect, useState } from "react";

import {
  confirmPlan,
  createUser,
  fetchApiHealth,
  fetchLanguageCourses,
  generatePlanDraft,
} from "./api";
import { ApiRequestError } from "./types";
import type { ApiHealth, CreatedPlanResponse, LanguageCourse, LearningMode, PlanDraft, UserProfile } from "./types";

type ApiHealthState =
  | { status: "loading" }
  | { status: "online"; data: ApiHealth }
  | { status: "offline"; message: string };

type AsyncActionState =
  | { status: "idle" }
  | { status: "loading"; label: string }
  | { status: "error"; code: string; message: string; recoverable: boolean };

function App() {
  const [apiHealth, setApiHealth] = useState<ApiHealthState>({ status: "loading" });
  const [courses, setCourses] = useState<LanguageCourse[]>([]);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [planDraft, setPlanDraft] = useState<PlanDraft | null>(null);
  const [createdPlan, setCreatedPlan] = useState<CreatedPlanResponse | null>(null);
  const [actionState, setActionState] = useState<AsyncActionState>({ status: "idle" });
  const [displayName, setDisplayName] = useState("Pinking");
  const [mode, setMode] = useState<LearningMode>("goal_based");
  const [goalText, setGoalText] = useState("两周内掌握 DOM 事件，并能验证 AI 生成代码。");
  const [materialTitle, setMaterialTitle] = useState("已有学习材料");
  const [materialContent, setMaterialContent] = useState("");
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const deferredGoalText = useDeferredValue(goalText);
  const selectedCourse = courses.find((course) => course.id === selectedCourseId) ?? courses[0] ?? null;
  const canGenerate =
    apiHealth.status === "online" &&
    selectedCourse !== null &&
    displayName.trim().length > 0 &&
    (mode === "goal_based" ? goalText.trim().length > 0 : materialContent.trim().length > 0);
  const isBusy = actionState.status === "loading";

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
        setActionState({ status: "idle" });
      });
    } catch (error) {
      setActionState(toActionError(error));
    }
  }

  async function handleConfirm() {
    if (!user || !planDraft) {
      return;
    }
    setActionState({ status: "loading", label: "正在确认正式学习计划" });
    try {
      const response = await confirmPlan(user.id, planDraft);
      startTransition(() => {
        setCreatedPlan(response);
        setActionState({ status: "idle" });
      });
    } catch (error) {
      setActionState(toActionError(error));
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void bootstrap(controller.signal);

    return () => controller.abort();
  }, []);

  if (createdPlan) {
    return (
      <main className="app-shell">
        <TopStatus apiHealth={apiHealth} onRetry={() => void bootstrap()} />
        <section className="workspace" aria-labelledby="workspace-title">
          <p className="eyebrow">Milestone 2 Workspace</p>
          <h1 id="workspace-title">学习计划已创建</h1>
          <p className="summary">
            当前只进入基础学习工作台入口。代码练习卡片、运行预览、提交评分和 Attempt 留痕从 M3 开始实现。
          </p>

          <div className="workspace-grid">
            <article className="panel">
              <h2>{createdPlan.LearningPlan.goal_text}</h2>
              <p>
                课程：{courseLabel(courses, createdPlan.LearningPlan.language_course_id)} / 入口知识点：
                {createdPlan.next_entry_point.knowledge_point_id ?? "待生成"}
              </p>
              <p>模块数：{createdPlan.modules.length}，知识点数：{createdPlan.knowledge_points.length}</p>
            </article>
            <article className="panel route-panel">
              <h2>路线面板</h2>
              {createdPlan.modules.map((module) => (
                <div className="route-module" key={module.id}>
                  <div>
                    <strong>{module.title}</strong>
                    <span>{module.is_skippable ? "可调整模块" : "核心模块，不可跳过"}</span>
                  </div>
                  <ul>
                    {createdPlan.knowledge_points
                      .filter((knowledgePoint) => knowledgePoint.module_id === module.id)
                      .map((knowledgePoint) => (
                        <li key={knowledgePoint.id}>{knowledgePoint.title}</li>
                      ))}
                  </ul>
                </div>
              ))}
            </article>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <TopStatus apiHealth={apiHealth} onRetry={() => void bootstrap()} />
      <section className="hero onboarding" aria-labelledby="app-title">
        <div>
          <p className="eyebrow">Milestone 2</p>
          <h1 id="app-title">Aearn Onboarding</h1>
          <p className="summary">
            输入目标或学习资料，选择固定课程模板，生成可确认的学习计划草稿。M2 只创建计划和复习初始化，不进入练习运行。
          </p>
        </div>

        <div className="onboarding-grid">
          <section className="panel form-panel" aria-label="计划生成表单">
            <label>
              显示名称
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={isBusy} />
            </label>

            <div className="mode-tabs" role="tablist" aria-label="Onboarding mode">
              <button
                aria-selected={mode === "goal_based"}
                className={mode === "goal_based" ? "active" : ""}
                type="button"
                onClick={() => setMode("goal_based")}
              >
                目标驱动
              </button>
              <button
                aria-selected={mode === "material_based"}
                className={mode === "material_based" ? "active" : ""}
                type="button"
                onClick={() => setMode("material_based")}
              >
                资料驱动
              </button>
            </div>

            {mode === "goal_based" ? (
              <label>
                学习目标
                <textarea value={goalText} onChange={(event) => setGoalText(event.target.value)} disabled={isBusy} />
              </label>
            ) : (
              <>
                <label>
                  资料标题
                  <input value={materialTitle} onChange={(event) => setMaterialTitle(event.target.value)} disabled={isBusy} />
                </label>
                <label>
                  资料内容
                  <textarea
                    value={materialContent}
                    onChange={(event) => setMaterialContent(event.target.value)}
                    disabled={isBusy}
                    placeholder="粘贴你已有的笔记、代码片段或知识点列表"
                  />
                </label>
              </>
            )}

            <div className="course-list" aria-label="课程选择">
              {courses.map((course) => (
                <button
                  className={course.id === selectedCourse?.id ? "course-card active" : "course-card"}
                  key={course.id}
                  type="button"
                  onClick={() => {
                    setSelectedCourseId(course.id);
                    setPlanDraft(null);
                  }}
                  disabled={isBusy}
                >
                  <strong>{course.title}</strong>
                  <span>{runtimeLabel(course.runtime_profile.runtime_tier)}</span>
                </button>
              ))}
            </div>

            {selectedCourse?.runtime_profile.runtime_tier === "compiled_sandbox_later" && (
              <div className="notice notice--warning">
                Java/C++ 第一版只展示静态阅读和补全边界，不提供完整编译运行沙箱。
              </div>
            )}

            <button className="primary-action" type="button" onClick={() => void handleGenerate()} disabled={!canGenerate || isBusy}>
              {isBusy ? "处理中" : "生成计划草稿"}
            </button>
            {!canGenerate && <p className="disabled-reason">需要 API 在线、选择课程，并填写目标或资料内容。</p>}
          </section>

          <PlanDraftPreview
            actionState={actionState}
            planDraft={planDraft}
            selectedCourse={selectedCourse}
            onConfirm={() => void handleConfirm()}
            isBusy={isBusy}
          />
        </div>
      </section>
    </main>
  );
}

function PlanDraftPreview({
  actionState,
  planDraft,
  selectedCourse,
  onConfirm,
  isBusy,
}: {
  actionState: AsyncActionState;
  planDraft: PlanDraft | null;
  selectedCourse: LanguageCourse | null;
  onConfirm: () => void;
  isBusy: boolean;
}) {
  return (
    <section className="panel preview-panel" aria-label="计划草稿预览">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Plan Draft</p>
          <h2>计划草稿</h2>
        </div>
        {selectedCourse && <span className="runtime-pill">{runtimeLabel(selectedCourse.runtime_profile.runtime_tier)}</span>}
      </div>

      {actionState.status === "loading" && <div className="notice">{actionState.label}</div>}
      {actionState.status === "error" && (
        <div className="notice notice--error">
          {actionState.code}: {actionState.message}
        </div>
      )}

      {!planDraft ? (
        <div className="empty-state">草稿生成后会展示模块、知识点、来源归因和运行能力边界。</div>
      ) : (
        <>
          <div className="notice">
            {planDraft.runtime_boundary.notice}
          </div>
          <div className="source-list">
            <strong>来源归因</strong>
            {planDraft.source_attribution.map((source) => (
              <span key={source}>{source}</span>
            ))}
          </div>
          <div className="draft-modules">
            {planDraft.modules.map((module) => (
              <article className="draft-module" key={module.temp_id}>
                <div className="module-title-row">
                  <h3>{module.title}</h3>
                  <span>{module.is_skippable ? "可跳过" : "核心模块，不可跳过"}</span>
                </div>
                <p>{module.description}</p>
                <ul>
                  {module.knowledge_points.map((knowledgePoint) => (
                    <li key={knowledgePoint.temp_id}>
                      <strong>{knowledgePoint.title}</strong>
                      <span>{knowledgePoint.description}</span>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
          <button className="primary-action" type="button" onClick={onConfirm} disabled={isBusy}>
            确认学习计划
          </button>
        </>
      )}
    </section>
  );
}

function TopStatus({ apiHealth, onRetry }: { apiHealth: ApiHealthState; onRetry: () => void }) {
  return (
    <aside className={`top-status top-status--${apiHealth.status}`} aria-label="API 状态">
      <span>API 状态</span>
      <strong>
        {apiHealth.status === "loading" && "检测中"}
        {apiHealth.status === "online" && `${apiHealth.data.service} 在线`}
        {apiHealth.status === "offline" && "离线"}
      </strong>
      {apiHealth.status === "offline" && (
        <>
          <em>{apiHealth.message}</em>
          <button type="button" onClick={onRetry}>
            重试
          </button>
        </>
      )}
    </aside>
  );
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

function courseLabel(courses: LanguageCourse[], courseId: string): string {
  return courses.find((course) => course.id === courseId)?.title ?? courseId;
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
