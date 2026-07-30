import { create } from "zustand";

import {
  confirmHarnessCutover,
  createUser,
  fetchApiHealth,
  fetchHarnessCutover,
  fetchLanguageCourses,
  fetchUserProfile,
} from "../api";
import { clearBootstrapContext, readBootstrapContext, writeBootstrapContext } from "../lib/bootstrapStorage";
import { getErrorInfo } from "../lib/errorMessages";
import type { HarnessCutoverDecision, UserProfile } from "../types";

export type AppRoute = "loading" | "welcome" | "cutover" | "tutor";
export type ApiHealthState =
  | { status: "checking" }
  | { status: "online" }
  | { status: "offline"; message: string };
export type DataActionState = "idle" | "loading" | "success" | "error";

type AppState = {
  activeRoute: AppRoute;
  apiHealth: ApiHealthState;
  bootstrapHydrated: boolean;
  sidebarOpen: boolean;
  user: UserProfile | null;
  cutoverDecision: HarnessCutoverDecision | null;
  dataActionState: DataActionState;
  dataActionMessage: string | null;
  bootstrap: (signal?: AbortSignal) => Promise<void>;
  createLocalUser: (displayName: string) => Promise<boolean>;
  refreshHarnessCutover: () => Promise<void>;
  confirmHarnessCutover: () => Promise<boolean>;
  toggleSidebar: () => void;
};

export const useAppStore = create<AppState>((set, get) => ({
  activeRoute: "loading",
  apiHealth: { status: "checking" },
  bootstrapHydrated: false,
  sidebarOpen: true,
  user: null,
  cutoverDecision: null,
  dataActionState: "idle",
  dataActionMessage: null,

  bootstrap: async (signal) => {
    set({ activeRoute: "loading", bootstrapHydrated: false, dataActionMessage: null });
    const [healthResult, catalogResult] = await Promise.allSettled([
      fetchApiHealth(signal),
      fetchLanguageCourses(signal),
    ]);
    if (signal?.aborted) return;
    if (healthResult.status === "fulfilled") {
      set({ apiHealth: { status: "online" } });
    } else {
      set({ apiHealth: { status: "offline", message: getErrorInfo(healthResult.reason).message } });
    }
    if (catalogResult.status === "rejected" && healthResult.status === "fulfilled") {
      set({ dataActionMessage: `课程目录暂不可用：${getErrorInfo(catalogResult.reason).message}` });
    }

    const stored = readBootstrapContext();
    if (!stored.userId) {
      set({ activeRoute: "welcome", bootstrapHydrated: true });
      return;
    }

    try {
      const user = await fetchUserProfile(stored.userId, signal);
      if (signal?.aborted) return;
      writeBootstrapContext({ userId: user.id, planId: null });
      const decision = await fetchHarnessCutover(user.id, signal);
      if (signal?.aborted) return;
      set({
        user,
        cutoverDecision: decision,
        activeRoute: routeForDecision(decision),
        bootstrapHydrated: true,
        dataActionState: "idle",
      });
    } catch (error) {
      if (signal?.aborted) return;
      clearBootstrapContext();
      set({
        user: null,
        cutoverDecision: null,
        activeRoute: "welcome",
        bootstrapHydrated: true,
        dataActionState: "error",
        dataActionMessage: `无法恢复本地身份：${getErrorInfo(error).message}`,
      });
    }
  },

  createLocalUser: async (displayName) => {
    const normalized = displayName.trim();
    if (!normalized) {
      set({ dataActionState: "error", dataActionMessage: "请先填写一个显示名称。" });
      return false;
    }
    set({ dataActionState: "loading", dataActionMessage: null });
    try {
      const user = await createUser(normalized);
      writeBootstrapContext({ userId: user.id, planId: null });
      const decision = await fetchHarnessCutover(user.id);
      set({
        user,
        cutoverDecision: decision,
        activeRoute: routeForDecision(decision),
        bootstrapHydrated: true,
        dataActionState: "success",
        dataActionMessage: decision.state === "verified" ? "已创建本地身份，欢迎开始你的学习目标。" : null,
      });
      return true;
    } catch (error) {
      set({ dataActionState: "error", dataActionMessage: getErrorInfo(error).message });
      return false;
    }
  },

  refreshHarnessCutover: async () => {
    const user = get().user;
    if (!user) return;
    set({ dataActionState: "loading", dataActionMessage: null });
    try {
      const decision = await fetchHarnessCutover(user.id);
      set({
        cutoverDecision: decision,
        activeRoute: routeForDecision(decision),
        dataActionState: "idle",
        dataActionMessage: null,
      });
    } catch (error) {
      set({ dataActionState: "error", dataActionMessage: getErrorInfo(error).message });
    }
  },

  confirmHarnessCutover: async () => {
    const { user, cutoverDecision } = get();
    if (!user || !cutoverDecision || cutoverDecision.state !== "summary_ready") {
      set({ dataActionState: "error", dataActionMessage: "当前没有可确认的服务器清理摘要。" });
      return false;
    }
    const { cutover_version, summary_version, preview_nonce, summary_hash } = cutoverDecision;
    if (summary_version === undefined || !preview_nonce || !summary_hash) {
      set({ dataActionState: "error", dataActionMessage: "服务器摘要不完整，请先刷新。" });
      return false;
    }
    set({ dataActionState: "loading", dataActionMessage: null });
    try {
      const decision = await confirmHarnessCutover({
        userId: user.id,
        cutoverVersion: cutover_version,
        summaryVersion: summary_version,
        previewNonce: preview_nonce,
        summaryHash: summary_hash,
        clientActionId: `cutover:${user.id}:${Date.now()}:${Math.random().toString(16).slice(2)}`,
      });
      writeBootstrapContext({ userId: user.id, planId: null });
      const enteredTutor = decision.state === "verified";
      set({
        cutoverDecision: decision,
        activeRoute: routeForDecision(decision),
        dataActionState: enteredTutor ? "success" : "error",
        dataActionMessage: enteredTutor ? "旧学习记录已按服务器摘要清理，已进入新的 Tutor 工作区。" : "服务器未允许进入 Tutor，请查看当前状态。",
      });
      return enteredTutor;
    } catch (error) {
      set({ dataActionState: "error", dataActionMessage: getErrorInfo(error).message });
      return false;
    }
  },

  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
}));

function routeForDecision(decision: HarnessCutoverDecision): AppRoute {
  return decision.state === "verified" ? "tutor" : "cutover";
}
