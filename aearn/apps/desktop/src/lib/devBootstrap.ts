import { isRecord } from "./typeGuards";

type BootstrapContext = { userId: string; planId: string | null };

const DEV_BOOTSTRAP_SCHEMA_VERSION = "aearn_dev_bootstrap_v1";

export async function readDevBootstrapContext(signal?: AbortSignal): Promise<BootstrapContext | null> {
  if (!isDevBuild()) {
    return null;
  }
  try {
    const response = await fetch(`/aearn-dev-bootstrap.json?ts=${Date.now()}`, {
      cache: "no-store",
      signal,
    });
    if (!response.ok) {
      return null;
    }
    const payload: unknown = await response.json();
    if (!isRecord(payload) || payload.schemaVersion !== DEV_BOOTSTRAP_SCHEMA_VERSION || payload.enabled !== true) {
      return null;
    }
    if (typeof payload.userId !== "string" || !payload.userId) {
      return null;
    }
    return {
      userId: payload.userId,
      planId: typeof payload.planId === "string" && payload.planId ? payload.planId : null,
    };
  } catch {
    return null;
  }
}

function isDevBuild(): boolean {
  return import.meta.env.DEV;
}
