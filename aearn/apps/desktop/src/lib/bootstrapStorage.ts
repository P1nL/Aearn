import { isRecord } from "./typeGuards";

export function readBootstrapContext(): { userId: string | null; planId: string | null } {
  if (typeof window === "undefined") {
    return { userId: null, planId: null };
  }
  try {
    const raw = window.localStorage.getItem("aearn.bootstrap");
    if (!raw) {
      return { userId: null, planId: null };
    }
    const parsed = JSON.parse(raw);
    if (!isRecord(parsed)) {
      return { userId: null, planId: null };
    }
    return {
      userId: typeof parsed.userId === "string" ? parsed.userId : null,
      planId: typeof parsed.planId === "string" ? parsed.planId : null,
    };
  } catch {
    return { userId: null, planId: null };
  }
}

export function writeBootstrapContext(value: { userId: string; planId: string | null }) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem("aearn.bootstrap", JSON.stringify(value));
}

export function clearBootstrapContext() {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem("aearn.bootstrap");
}
