import { create } from "zustand";

import {
  API_BASE_URL,
  deleteLocalUser,
  exportLocalUserData,
  fetchApiHealth,
  fetchDashboard,
  fetchLanguageCourses,
  fetchLocalUsers,
  fetchPlanDetail,
  fetchResumeContext,
  fetchUserDataSummary,
  fetchUserProfile,
  resetLocalUserData,
  startLearningSession,
} from "../api";
import type {
  ApiHealthState,
  AppRoute,
  ConversationMessage,
  ConversationToolCall,
  LocalUsersState,
  NavGroupKey,
  SessionState,
  UserDataSummaryState,
} from "../appTypes";
import { parsePartial } from "../lib/partialJson";
import type {
  CreatedPlanResponse,
  DashboardResponse,
  LanguageCourse,
  LocalUserExportPayload,
  LocalUserListItem,
  RunExerciseResponse,
  SubmitExerciseResponse,
  UserProfile,
} from "../types";
import { ApiRequestError } from "../types";
import { NAV_DEFAULTS } from "../lib/appContent";
import { formatErrorMessage } from "../lib/errorMessages";
import { applyKnowledgePointUpdate, markKnowledgePointLearning } from "../lib/learningHelpers";
import { clearBootstrapContext, readBootstrapContext, writeBootstrapContext } from "../lib/bootstrapStorage";

export type DashboardState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: DashboardResponse }
  | { status: "error"; message: string };

type ConversationMessagePatch = Partial<ConversationMessage> & {
  appendText?: string;
};

type AppStore = {
  apiHealth: ApiHealthState;
  dashboardState: DashboardState;
  courses: LanguageCourse[];
  user: UserProfile | null;
  createdPlan: CreatedPlanResponse | null;
  sessionState: SessionState;
  localUsersState: LocalUsersState;
  userDataSummaryState: UserDataSummaryState;
  dataActionState: "idle" | "loading" | "success" | "error";
  dataActionMessage: string | null;
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

  // Onboarding conversation state
  onboardingMessages: ConversationMessage[];
  onboardingSessionId: string | null;

  // Simple setters
  setUser: (user: UserProfile | null) => void;
  setCreatedPlan: (plan: CreatedPlanResponse | null) => void;
  setActiveRoute: (route: AppRoute) => void;
  setLastRun: (run: RunExerciseResponse | null) => void;
  setLastSubmit: (submit: SubmitExerciseResponse | null) => void;
  clearLearningSession: () => void;
  clearUserScopedState: (options?: { keepUser?: UserProfile | null; route?: AppRoute }) => void;
  setComposerInput: (input: string) => void;
  toggleSidebar: () => void;
  toggleGroup: (group: NavGroupKey) => void;
  addHomeMessage: (msg: ConversationMessage) => void;
  updateHomeMessage: (id: string, patch: ConversationMessagePatch) => void;
  addReviewMessage: (msg: ConversationMessage) => void;
  updateReviewMessage: (id: string, patch: ConversationMessagePatch) => void;

  // Onboarding conversation actions
  addOnboardingMessage: (msg: ConversationMessage) => void;
  updateOnboardingMessage: (id: string, patch: ConversationMessagePatch) => void;
  setOnboardingSessionId: (id: string | null) => void;

  // Tool call state machine (currently scoped to onboarding messages)
  startOnboardingToolCall: (messageId: string, toolCallId: string, name: string) => void;
  appendOnboardingToolCallDelta: (messageId: string, toolCallId: string, delta: string) => void;
  finalizeOnboardingToolCall: (messageId: string, toolCallId: string, args: unknown) => void;
  startHomeToolCall: (messageId: string, toolCallId: string, name: string) => void;
  appendHomeToolCallDelta: (messageId: string, toolCallId: string, delta: string) => void;
  finalizeHomeToolCall: (messageId: string, toolCallId: string, args: unknown) => void;

  // Complex actions
  bootstrap: (signal?: AbortSignal) => Promise<void>;
  refreshDashboard: (activeUserId?: string, signal?: AbortSignal) => Promise<void>;
  loadLocalUsers: (signal?: AbortSignal) => Promise<void>;
  loadUserDataSummary: (activeUserId?: string, signal?: AbortSignal) => Promise<void>;
  switchLocalUser: (item: LocalUserListItem) => Promise<void>;
  exportActiveUserData: () => Promise<LocalUserExportPayload | null>;
  resetActiveUserData: () => Promise<boolean>;
  deleteActiveUser: () => Promise<boolean>;
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
  localUsersState: { status: "idle" },
  userDataSummaryState: { status: "idle" },
  dataActionState: "idle",
  dataActionMessage: null,
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
  onboardingMessages: [],
  onboardingSessionId: null,

  setUser: (user) => set({ user }),
  setCreatedPlan: (plan) => set({ createdPlan: plan }),
  setActiveRoute: (route) => set({ activeRoute: route }),
  setLastRun: (run) => set({ lastRun: run }),
  setLastSubmit: (submit) => set({ lastSubmit: submit }),
  clearLearningSession: () => set({ sessionState: { status: "idle" }, lastRun: null, lastSubmit: null, homeConversation: [] }),
  clearUserScopedState: (options) =>
    set({
      user: options?.keepUser ?? null,
      createdPlan: null,
      sessionState: { status: "idle" },
      dashboardState: { status: "idle" },
      lastRun: null,
      lastSubmit: null,
      homeConversation: [],
      reviewConversation: [],
      onboardingMessages: [],
      onboardingSessionId: null,
      composerInput: "",
      activeRoute: options?.route ?? "onboarding",
      resetNonce: get().resetNonce + 1,
    }),
  setComposerInput: (input) => set({ composerInput: input }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  toggleGroup: (group) => set((s) => ({ openGroups: { ...s.openGroups, [group]: !s.openGroups[group] } })),
  addHomeMessage: (msg) => set((s) => ({ homeConversation: [...s.homeConversation, msg] })),
  updateHomeMessage: (id, patch) =>
    set((s) => ({
      homeConversation: s.homeConversation.map((message) => {
        if (message.id !== id) {
          return message;
        }
        const { appendText, ...messagePatch } = patch;
        return {
          ...message,
          ...messagePatch,
          text: appendText ? `${message.text}${appendText}` : (messagePatch.text ?? message.text),
        };
      }),
    })),
  addReviewMessage: (msg) => set((s) => ({ reviewConversation: [...s.reviewConversation, msg] })),
  updateReviewMessage: (id, patch) =>
    set((s) => ({
      reviewConversation: s.reviewConversation.map((message) => {
        if (message.id !== id) {
          return message;
        }
        const { appendText, ...messagePatch } = patch;
        return {
          ...message,
          ...messagePatch,
          text: appendText ? `${message.text}${appendText}` : (messagePatch.text ?? message.text),
        };
      }),
    })),
  addOnboardingMessage: (msg) => set((s) => ({ onboardingMessages: [...s.onboardingMessages, msg] })),
  updateOnboardingMessage: (id, patch) =>
    set((s) => ({
      onboardingMessages: s.onboardingMessages.map((message) => {
        if (message.id !== id) {
          return message;
        }
        const { appendText, ...messagePatch } = patch;
        return {
          ...message,
          ...messagePatch,
          text: appendText ? `${message.text}${appendText}` : (messagePatch.text ?? message.text),
        };
      }),
    })),
  setOnboardingSessionId: (id) => set({ onboardingSessionId: id }),

  startOnboardingToolCall: (messageId, toolCallId, name) =>
    set((s) => ({
      onboardingMessages: s.onboardingMessages.map((message) => {
        if (message.id !== messageId) return message;
        const existing = message.toolCalls ?? [];
        if (existing.some((entry) => entry.id === toolCallId)) {
          return message;
        }
        const toolCall: ConversationToolCall = {
          id: toolCallId,
          name,
          args: null,
          argsBuffer: "",
          status: "pending",
        };
        return { ...message, toolCalls: [...existing, toolCall] };
      }),
    })),
  appendOnboardingToolCallDelta: (messageId, toolCallId, delta) =>
    set((s) => ({
      onboardingMessages: s.onboardingMessages.map((message) => {
        if (message.id !== messageId) return message;
        const existing = message.toolCalls ?? [];
        if (existing.length === 0) return message;
        return {
          ...message,
          toolCalls: existing.map((entry) => {
            if (entry.id !== toolCallId) return entry;
            const nextBuffer = `${entry.argsBuffer}${delta}`;
            const parsed = parsePartial(nextBuffer);
            return {
              ...entry,
              argsBuffer: nextBuffer,
              args: parsed ?? entry.args,
              status: "running" as const,
            };
          }),
        };
      }),
    })),
  finalizeOnboardingToolCall: (messageId, toolCallId, args) =>
    set((s) => ({
      onboardingMessages: s.onboardingMessages.map((message) => {
        if (message.id !== messageId) return message;
        const existing = message.toolCalls ?? [];
        if (existing.length === 0) return message;
        return {
          ...message,
          toolCalls: existing.map((entry) =>
            entry.id === toolCallId
              ? { ...entry, args, status: "done" as const }
              : entry,
          ),
        };
      }),
    })),

  startHomeToolCall: (messageId, toolCallId, name) =>
    set((s) => ({
      homeConversation: s.homeConversation.map((message) => {
        if (message.id !== messageId) return message;
        const existing = message.toolCalls ?? [];
        if (existing.some((entry) => entry.id === toolCallId)) {
          return message;
        }
        const toolCall: ConversationToolCall = {
          id: toolCallId,
          name,
          args: null,
          argsBuffer: "",
          status: "pending",
        };
        return { ...message, toolCalls: [...existing, toolCall] };
      }),
    })),
  appendHomeToolCallDelta: (messageId, toolCallId, delta) =>
    set((s) => ({
      homeConversation: s.homeConversation.map((message) => {
        if (message.id !== messageId) return message;
        const existing = message.toolCalls ?? [];
        if (existing.length === 0) return message;
        return {
          ...message,
          toolCalls: existing.map((entry) => {
            if (entry.id !== toolCallId) return entry;
            const nextBuffer = `${entry.argsBuffer}${delta}`;
            const parsed = parsePartial(nextBuffer);
            return {
              ...entry,
              argsBuffer: nextBuffer,
              args: parsed ?? entry.args,
              status: "running" as const,
            };
          }),
        };
      }),
    })),
  finalizeHomeToolCall: (messageId, toolCallId, args) =>
    set((s) => ({
      homeConversation: s.homeConversation.map((message) => {
        if (message.id !== messageId) return message;
        const existing = message.toolCalls ?? [];
        if (existing.length === 0) return message;
        return {
          ...message,
          toolCalls: existing.map((entry) =>
            entry.id === toolCallId
              ? { ...entry, args, status: "done" as const }
              : entry,
          ),
        };
      }),
    })),

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
        fetchPlanDetail(stored.planId, stored.userId, signal),
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

  loadLocalUsers: async (signal) => {
    set({ localUsersState: { status: "loading" } });
    try {
      const response = await fetchLocalUsers(signal);
      if (signal?.aborted) return;
      set({ localUsersState: { status: "ready", items: response.items } });
    } catch (error) {
      if (signal?.aborted) return;
      set({ localUsersState: { status: "error", message: formatErrorMessage(error, "无法读取本地用户") } });
    }
  },

  loadUserDataSummary: async (activeUserId, signal) => {
    const userId = activeUserId ?? get().user?.id;
    if (!userId) {
      set({ userDataSummaryState: { status: "idle" } });
      return;
    }
    set({ userDataSummaryState: { status: "loading" } });
    try {
      const summary = await fetchUserDataSummary(userId, signal);
      if (signal?.aborted) return;
      set({ userDataSummaryState: { status: "ready", data: summary } });
    } catch (error) {
      if (signal?.aborted) return;
      set({ userDataSummaryState: { status: "error", message: formatErrorMessage(error, "无法读取本地记录摘要") } });
    }
  },

  switchLocalUser: async (item) => {
    set({ dataActionState: "loading", dataActionMessage: "正在切换本地用户..." });
    try {
      const loadedUser = await fetchUserProfile(item.id);
      writeBootstrapContext({ userId: loadedUser.id, planId: null });
      get().clearUserScopedState({ keepUser: loadedUser, route: "onboarding" });
      set({ user: loadedUser, dataActionState: "success", dataActionMessage: "已切换本地用户" });
      if (item.active_plan_id) {
        const [plan, dashboardResponse] = await Promise.all([
          fetchPlanDetail(item.active_plan_id, item.id),
          fetchDashboard(item.id),
        ]);
        writeBootstrapContext({ userId: item.id, planId: plan.LearningPlan.id });
        set({ createdPlan: plan, dashboardState: { status: "ready", data: dashboardResponse } });
        const next = dashboardResponse.next_entry_point;
        if (next.type === "review") {
          set({ activeRoute: "review" });
        } else if (next.type === "resume") {
          const resume = await fetchResumeContext(item.id, plan.LearningPlan.id);
          if (resume.next_entry_point.knowledge_point_id) {
            await get().openLearningSession(plan, resume.next_entry_point.knowledge_point_id, item.id);
          } else {
            set({ activeRoute: "home" });
          }
        } else if (next.knowledge_point_id) {
          await get().openLearningSession(plan, next.knowledge_point_id, item.id);
        } else {
          set({ activeRoute: "home" });
        }
      }
      void get().loadLocalUsers();
      void get().loadUserDataSummary(item.id);
    } catch (error) {
      set({ dataActionState: "error", dataActionMessage: formatErrorMessage(error, "切换本地用户失败") });
    }
  },

  exportActiveUserData: async () => {
    const user = get().user;
    if (!user) return null;
    set({ dataActionState: "loading", dataActionMessage: "正在生成导出文件..." });
    try {
      const payload = await exportLocalUserData(user.id);
      const filename = `aearn-export-${user.display_name || "user"}-${new Date().toISOString().slice(0, 10)}.json`;
      downloadJson(filename, payload);
      set({ dataActionState: "success", dataActionMessage: "导出文件已生成" });
      return payload;
    } catch (error) {
      set({ dataActionState: "error", dataActionMessage: formatErrorMessage(error, "导出本地记录失败") });
      return null;
    }
  },

  resetActiveUserData: async () => {
    const user = get().user;
    if (!user) return false;
    set({ dataActionState: "loading", dataActionMessage: "正在重置学习数据..." });
    try {
      const response = await resetLocalUserData(user.id);
      writeBootstrapContext({ userId: response.user.id, planId: null });
      get().clearUserScopedState({ keepUser: response.user, route: "onboarding" });
      set({
        user: response.user,
        userDataSummaryState: { status: "ready", data: response.summary },
        dataActionState: "success",
        dataActionMessage: "学习数据已重置，用户资料和偏好已保留",
      });
      void get().loadLocalUsers();
      return true;
    } catch (error) {
      set({ dataActionState: "error", dataActionMessage: formatErrorMessage(error, "重置学习数据失败") });
      return false;
    }
  },

  deleteActiveUser: async () => {
    const user = get().user;
    if (!user) return false;
    set({ dataActionState: "loading", dataActionMessage: "正在删除本地用户..." });
    try {
      await deleteLocalUser(user.id);
      clearBootstrapContext();
      get().clearUserScopedState({ keepUser: null, route: "onboarding" });
      set({
        userDataSummaryState: { status: "idle" },
        dataActionState: "success",
        dataActionMessage: "本地用户已删除",
      });
      void get().loadLocalUsers();
      return true;
    } catch (error) {
      set({ dataActionState: "error", dataActionMessage: formatErrorMessage(error, "删除本地用户失败") });
      return false;
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
        homeConversation: [],
        createdPlan: markKnowledgePointLearning(get().createdPlan ?? planResponse, knowledgePointId),
        ...(activateHome ? { activeRoute: "home" as const } : {}),
      });
      void get().refreshDashboard(userId);
    } catch (error) {
      set({
        sessionState: { status: "error", knowledgePointId, message: formatErrorMessage(error, "无法启动学习会话") },
        ...(activateHome ? { activeRoute: "home" as const } : {}),
      });
    }
  },

  handlePlanCreated: async (plan, activeUser) => {
    writeBootstrapContext({ userId: activeUser.id, planId: plan.LearningPlan.id });
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
      onboardingMessages: [],
      onboardingSessionId: null,
      composerInput: "",
      activeRoute: "onboarding",
      resetNonce: get().resetNonce + 1,
    });
  },
}));

function downloadJson(filename: string, payload: unknown) {
  if (typeof window === "undefined") {
    return;
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename.replace(/[\\/:*?"<>|]/g, "_");
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}
