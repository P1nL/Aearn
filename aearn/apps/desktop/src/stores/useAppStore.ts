import { create } from "zustand";

import {
  API_BASE_URL,
  fetchApiHealth,
  fetchDashboard,
  fetchLanguageCourses,
  fetchPlanDetail,
  fetchResumeContext,
  fetchUserProfile,
  startLearningSession,
} from "../api";
import type {
  ApiHealthState,
  AppRoute,
  ConversationMessage,
  NavGroupKey,
  SessionState,
} from "../appTypes";
import type {
  CreatedPlanResponse,
  DashboardResponse,
  LanguageCourse,
  RunExerciseResponse,
  SubmitExerciseResponse,
  UserProfile,
} from "../types";
import { ApiRequestError } from "../types";
import { NAV_DEFAULTS } from "../lib/appContent";
import { formatErrorMessage } from "../lib/errorMessages";
import { applyKnowledgePointUpdate, markKnowledgePointLearning } from "../lib/learningHelpers";
import { clearBootstrapContext, readBootstrapContext } from "../lib/bootstrapStorage";

export type DashboardState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: DashboardResponse }
  | { status: "error"; message: string };

type AppStore = {
  apiHealth: ApiHealthState;
  dashboardState: DashboardState;
  courses: LanguageCourse[];
  user: UserProfile | null;
  createdPlan: CreatedPlanResponse | null;
  sessionState: SessionState;
  bootstrapHydrated: boolean;
  lastRun: RunExerciseResponse | null;
  lastSubmit: SubmitExerciseResponse | null;
  activeRoute: AppRoute;
  sidebarOpen: boolean;
  openGroups: Record<NavGroupKey, boolean>;
  composerInput: string;
  homeConversation: ConversationMessage[];
  reviewConversation: ConversationMessage[];
  resetNonce: number;

  // Simple setters
  setUser: (user: UserProfile | null) => void;
  setCreatedPlan: (plan: CreatedPlanResponse | null) => void;
  setActiveRoute: (route: AppRoute) => void;
  setLastRun: (run: RunExerciseResponse | null) => void;
  setLastSubmit: (submit: SubmitExerciseResponse | null) => void;
  setComposerInput: (input: string) => void;
  toggleSidebar: () => void;
  toggleGroup: (group: NavGroupKey) => void;
  addHomeMessage: (msg: ConversationMessage) => void;
  updateHomeMessage: (id: string, patch: Partial<ConversationMessage>) => void;
  addReviewMessage: (msg: ConversationMessage) => void;

  // Complex actions
  bootstrap: (signal?: AbortSignal) => Promise<void>;
  refreshDashboard: (activeUserId?: string, signal?: AbortSignal) => Promise<void>;
  openLearningSession: (planResponse: CreatedPlanResponse, knowledgePointId: string, activeUserId?: string, activateHome?: boolean) => Promise<void>;
  handlePlanCreated: (plan: CreatedPlanResponse, activeUser: UserProfile) => Promise<void>;
  handleKnowledgePointUpdate: (patch: SubmitExerciseResponse["KnowledgePoint"]) => void;
  handleResumeShortcut: () => Promise<void>;
  handleStartCurrentLearning: () => Promise<void>;
  resetGoal: () => void;
};

export const useAppStore = create<AppStore>((set, get) => ({
  apiHealth: { status: "loading" },
  dashboardState: { status: "idle" },
  courses: [],
  user: null,
  createdPlan: null,
  sessionState: { status: "idle" },
  bootstrapHydrated: false,
  lastRun: null,
  lastSubmit: null,
  activeRoute: "onboarding",
  sidebarOpen: true,
  openGroups: NAV_DEFAULTS,
  composerInput: "",
  homeConversation: [],
  reviewConversation: [],
  resetNonce: 0,

  setUser: (user) => set({ user }),
  setCreatedPlan: (plan) => set({ createdPlan: plan }),
  setActiveRoute: (route) => set({ activeRoute: route }),
  setLastRun: (run) => set({ lastRun: run }),
  setLastSubmit: (submit) => set({ lastSubmit: submit }),
  setComposerInput: (input) => set({ composerInput: input }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  toggleGroup: (group) => set((s) => ({ openGroups: { ...s.openGroups, [group]: !s.openGroups[group] } })),
  addHomeMessage: (msg) => set((s) => ({ homeConversation: [...s.homeConversation, msg] })),
  updateHomeMessage: (id, patch) =>
    set((s) => ({
      homeConversation: s.homeConversation.map((message) =>
        message.id === id ? { ...message, ...patch } : message,
      ),
    })),
  addReviewMessage: (msg) => set((s) => ({ reviewConversation: [...s.reviewConversation, msg] })),

  bootstrap: async (signal) => {
    set({ bootstrapHydrated: false, apiHealth: { status: "loading" }, dashboardState: { status: "loading" } });

    try {
      const [health, catalog] = await Promise.all([fetchApiHealth(signal), fetchLanguageCourses(signal)]);
      set({ apiHealth: { status: "online", data: health }, courses: catalog });

      const stored = readBootstrapContext();
      if (!stored.userId) {
        set({ dashboardState: { status: "idle" } });
        return;
      }

      const loadedUser = await fetchUserProfile(stored.userId, signal);
      if (signal?.aborted) return;
      set({ user: loadedUser });

      if (!stored.planId) {
        set({ createdPlan: null, sessionState: { status: "idle" }, dashboardState: { status: "idle" }, activeRoute: "onboarding" });
        return;
      }

      const [plan, dashboardResponse] = await Promise.all([
        fetchPlanDetail(stored.planId, signal),
        fetchDashboard(stored.userId, signal),
      ]);
      if (signal?.aborted) return;

      set({ createdPlan: plan, dashboardState: { status: "ready", data: dashboardResponse } });

      if (dashboardResponse.next_entry_point.type === "review") {
        set({ activeRoute: "review", sessionState: { status: "idle" } });
        return;
      }

      if (dashboardResponse.next_entry_point.type === "resume") {
        const resume = await fetchResumeContext(stored.userId, plan.LearningPlan.id, signal);
        if (signal?.aborted) return;
        if (resume.resume_available && resume.next_entry_point.knowledge_point_id) {
          await get().openLearningSession(plan, resume.next_entry_point.knowledge_point_id, stored.userId);
          return;
        }
        if (resume.next_entry_point.knowledge_point_id) {
          await get().openLearningSession(plan, resume.next_entry_point.knowledge_point_id, stored.userId);
          return;
        }
      }

      if (dashboardResponse.next_entry_point.type === "learning_session" && dashboardResponse.next_entry_point.knowledge_point_id) {
        await get().openLearningSession(plan, dashboardResponse.next_entry_point.knowledge_point_id, stored.userId);
        return;
      }

      set({ activeRoute: "home" });
    } catch (error) {
      if (signal?.aborted) return;
      if (error instanceof ApiRequestError && (error.apiError.code === "USER_NOT_FOUND" || error.apiError.code === "PLAN_NOT_FOUND")) {
        clearBootstrapContext();
        set({ user: null, createdPlan: null, sessionState: { status: "idle" }, activeRoute: "onboarding", dashboardState: { status: "idle" } });
        return;
      }
      set({
        apiHealth: { status: "offline", message: error instanceof Error ? error.message : "Unable to reach API service" },
        dashboardState: { status: "error", message: formatErrorMessage(error, "无法恢复 dashboard") },
      });
    } finally {
      if (!signal?.aborted) {
        set({ bootstrapHydrated: true });
      }
    }
  },

  refreshDashboard: async (activeUserId, signal) => {
    const userId = activeUserId ?? get().user?.id;
    if (!userId) {
      set({ dashboardState: { status: "idle" } });
      return;
    }
    try {
      const response = await fetchDashboard(userId, signal);
      if (signal?.aborted) return;
      set({ dashboardState: { status: "ready", data: response } });
    } catch (error) {
      if (signal?.aborted) return;
      set({ dashboardState: { status: "error", message: formatErrorMessage(error, "无法刷新 dashboard") } });
    }
  },

  openLearningSession: async (planResponse, knowledgePointId, activeUserId, activateHome = true) => {
    const userId = activeUserId ?? get().user?.id;
    if (!userId) {
      set({ sessionState: { status: "error", knowledgePointId, message: "请先完成用户建档" } });
      return;
    }

    set({ sessionState: { status: "loading", knowledgePointId }, lastRun: null, lastSubmit: null });
    try {
      const response = await startLearningSession({ userId, planId: planResponse.LearningPlan.id, knowledgePointId });
      set({
        sessionState: { status: "ready", data: response },
        createdPlan: markKnowledgePointLearning(get().createdPlan ?? planResponse, knowledgePointId),
        ...(activateHome ? { activeRoute: "home" as const } : {}),
      });
      void get().refreshDashboard(userId);
    } catch (error) {
      set({
        sessionState: { status: "error", knowledgePointId, message: error instanceof Error ? error.message : "无法启动学习会话" },
        ...(activateHome ? { activeRoute: "home" as const } : {}),
      });
    }
  },

  handlePlanCreated: async (plan, activeUser) => {
    set({ user: activeUser, createdPlan: plan, sessionState: { status: "idle" }, lastRun: null, lastSubmit: null, dashboardState: { status: "idle" } });
    const nextKnowledgePointId = plan.next_entry_point.knowledge_point_id;
    if (nextKnowledgePointId) {
      await get().openLearningSession(plan, nextKnowledgePointId, activeUser.id);
      return;
    }
    set({ activeRoute: "home" });
  },

  handleKnowledgePointUpdate: (patch) => {
    const { createdPlan, sessionState } = get();
    set({
      createdPlan: createdPlan ? applyKnowledgePointUpdate(createdPlan, patch) : createdPlan,
      sessionState:
        sessionState.status === "ready"
          ? {
              status: "ready",
              data: {
                ...sessionState.data,
                context_snapshot: {
                  ...sessionState.data.context_snapshot,
                  KnowledgePoint: { ...sessionState.data.context_snapshot.KnowledgePoint, status: patch.status },
                },
              },
            }
          : sessionState,
    });
    void get().refreshDashboard();
  },

  handleResumeShortcut: async () => {
    const { user, createdPlan } = get();
    if (!user || !createdPlan) return;
    try {
      const resume = await fetchResumeContext(user.id, createdPlan.LearningPlan.id);
      if (resume.next_entry_point.knowledge_point_id) {
        await get().openLearningSession(createdPlan, resume.next_entry_point.knowledge_point_id, user.id);
        return;
      }
      set({ activeRoute: "home" });
    } catch (error) {
      set({ dashboardState: { status: "error", message: formatErrorMessage(error, "无法恢复上次学习") } });
    }
  },

  handleStartCurrentLearning: async () => {
    const { createdPlan, dashboardState } = get();
    const dashboard = dashboardState.status === "ready" ? dashboardState.data : null;
    if (!createdPlan || !dashboard) return;
    const knowledgePointId =
      dashboard.next_entry_point.type === "learning_session"
        ? dashboard.next_entry_point.knowledge_point_id
        : dashboard.today_learning_tasks[0]?.knowledge_point_id ?? createdPlan.next_entry_point.knowledge_point_id;
    if (!knowledgePointId) {
      set({ activeRoute: "home" });
      return;
    }
    await get().openLearningSession(createdPlan, knowledgePointId);
  },

  resetGoal: () => {
    set({
      createdPlan: null,
      sessionState: { status: "idle" },
      dashboardState: { status: "idle" },
      lastRun: null,
      lastSubmit: null,
      homeConversation: [],
      reviewConversation: [],
      composerInput: "",
      activeRoute: "onboarding",
      resetNonce: get().resetNonce + 1,
    });
  },
}));
