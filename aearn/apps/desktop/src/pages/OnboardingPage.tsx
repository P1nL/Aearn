import { startTransition, useDeferredValue, useEffect, useState } from "react";

import { confirmPlan, createUser, generatePlanDraft } from "../api";
import type { ApiHealthState, AsyncActionState, ConversationMessage } from "../appTypes";
import { PlanDraftPanel } from "../features/onboarding/PlanDraftPanel";
import { ThreadMessages } from "../components/ThreadMessages";
import { runtimeLabel } from "../lib/desktopLabels";
import { toActionError } from "../lib/learningHelpers";
import type { CreatedPlanResponse, LanguageCourse, LearningMode, PlanDraft, UserProfile } from "../types";

type OnboardingPageProps = {
  apiHealth: ApiHealthState;
  courses: LanguageCourse[];
  existingUser: UserProfile | null;
  messages: ConversationMessage[];
  resetNonce: number;
  onUserChange: (user: UserProfile) => void;
  onPlanCreated: (plan: CreatedPlanResponse, user: UserProfile) => Promise<void> | void;
};

export function OnboardingPage({
  apiHealth,
  courses,
  existingUser,
  messages,
  resetNonce,
  onUserChange,
  onPlanCreated,
}: OnboardingPageProps) {
  const [actionState, setActionState] = useState<AsyncActionState>({ status: "idle" });
  const [displayName, setDisplayName] = useState("Pinking");
  const [mode, setMode] = useState<LearningMode>("goal_based");
  const [goalText, setGoalText] = useState("");
  const [materialTitle, setMaterialTitle] = useState("已有学习材料");
  const [materialContent, setMaterialContent] = useState("");
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [planDraft, setPlanDraft] = useState<PlanDraft | null>(null);
  const deferredGoalText = useDeferredValue(goalText);

  useEffect(() => {
    if (courses.length > 0 && !courses.some((course) => course.id === selectedCourseId)) {
      setSelectedCourseId(courses[0].id);
    }
  }, [courses, selectedCourseId]);

  useEffect(() => {
    setActionState({ status: "idle" });
    setDisplayName(existingUser?.display_name ?? "Pinking");
    setMode("goal_based");
    setGoalText("");
    setMaterialTitle("已有学习材料");
    setMaterialContent("");
    setSelectedCourseId("");
    setPlanDraft(null);
  }, [resetNonce]);

  const selectedCourse = courses.find((course) => course.id === selectedCourseId) ?? courses[0] ?? null;
  const canGenerate =
    apiHealth.status === "online" &&
    selectedCourse !== null &&
    displayName.trim().length > 0 &&
    (mode === "goal_based" ? goalText.trim().length > 0 : materialContent.trim().length > 0);
  const isBusy = actionState.status === "loading";

  async function ensureUser(): Promise<UserProfile> {
    if (existingUser) {
      return existingUser;
    }
    const created = await createUser(displayName.trim());
    onUserChange(created);
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
      await onPlanCreated(response, activeUser);
      startTransition(() => {
        setActionState({ status: "idle" });
      });
    } catch (error) {
      setActionState(toActionError(error));
    }
  }

  return (
    <div className="split-workspace">
      <div className="split-pane">
        <section className="conversation onboarding-conversation" aria-label="建档对话">
          <div className="thread">
            <ThreadMessages messages={messages} />
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
            <button className="btn primary" type="button" disabled={!canGenerate || isBusy} onClick={() => void (planDraft ? handleConfirm() : handleGenerate())}>
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
  );
}
