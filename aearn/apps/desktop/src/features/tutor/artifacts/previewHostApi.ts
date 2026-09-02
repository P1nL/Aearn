import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type PreviewHostScope = {
  artifactId: string;
  sourceArtifactId: string;
  sessionId: string;
  artifactVersion: number;
  languageId: string;
};

export type PreviewHostBounds = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type PreviewHostDescriptor = {
  hostId: string;
  nonce: string;
  scope: PreviewHostScope;
  generation: number;
};

export type PreviewHostEvent = {
  hostId: string;
  nonce: string;
  scope: PreviewHostScope;
  generation: number;
  sequence: number;
  event:
    | { kind: "ready" }
    | { kind: "console"; level: "log" | "info" | "warn" | "error"; message: string }
    | { kind: "runtime_error"; message: string }
    | { kind: "interaction_event"; event_key: string; payload_json: Readonly<Record<string, unknown>> };
};

export type PreviewHostApi = {
  available: () => boolean;
  create: (input: {
    scope: PreviewHostScope;
    source: string;
    sourceHash: string;
    bounds: PreviewHostBounds;
    visible: boolean;
  }) => Promise<PreviewHostDescriptor>;
  updateSource: (input: {
    descriptor: PreviewHostDescriptor;
    source: string;
    sourceHash: string;
  }) => Promise<PreviewHostDescriptor>;
  setBounds: (input: {
    descriptor: PreviewHostDescriptor;
    bounds: PreviewHostBounds;
    visible: boolean;
  }) => Promise<void>;
  recreate: (descriptor: PreviewHostDescriptor) => Promise<PreviewHostDescriptor>;
  close: (descriptor: PreviewHostDescriptor) => Promise<void>;
  listen: (listener: (event: PreviewHostEvent) => void) => Promise<() => void>;
};

const nativePreviewHostApi: PreviewHostApi = {
  available: isTauri,
  create: async (input) => requireDescriptor(await invoke("preview_host_create", { request: input })),
  updateSource: async ({ descriptor, source, sourceHash }) => requireDescriptor(await invoke("preview_host_update_source", {
    request: hostRequest(descriptor, { source, sourceHash }),
  })),
  setBounds: async ({ descriptor, bounds, visible }) => invoke("preview_host_set_bounds", {
    request: hostRequest(descriptor, { bounds, visible }),
  }),
  recreate: async (descriptor) => requireDescriptor(await invoke("preview_host_recreate", {
    request: hostRequest(descriptor),
  })),
  close: async (descriptor) => invoke("preview_host_close", { request: hostRequest(descriptor) }),
  listen: async (listener) => {
    const unlisten: UnlistenFn = await listen<unknown>("aearn-preview-event", ({ payload }) => {
      const event = parsePreviewHostEvent(payload);
      if (event) listener(event);
    });
    return unlisten;
  },
};

let testApi: PreviewHostApi | null = null;

export function previewHostApi(): PreviewHostApi {
  return testApi ?? nativePreviewHostApi;
}

export function setPreviewHostApiForTests(api: PreviewHostApi | null): void {
  testApi = api;
}

export function samePreviewScope(left: PreviewHostScope, right: PreviewHostScope): boolean {
  return left.artifactId === right.artifactId
    && left.sourceArtifactId === right.sourceArtifactId
    && left.sessionId === right.sessionId
    && left.artifactVersion === right.artifactVersion
    && left.languageId === right.languageId;
}

function hostRequest(
  descriptor: PreviewHostDescriptor,
  extra: Readonly<Record<string, unknown>> = {},
): Record<string, unknown> {
  return {
    hostId: descriptor.hostId,
    nonce: descriptor.nonce,
    scope: descriptor.scope,
    ...extra,
  };
}

function requireDescriptor(value: unknown): PreviewHostDescriptor {
  const descriptor = toPreviewHostDescriptor(value);
  if (!descriptor) throw new Error("PREVIEW_HOST_CONTRACT_ERROR");
  return descriptor;
}

function toPreviewHostDescriptor(value: unknown): PreviewHostDescriptor | null {
  if (!isRecord(value) || !hasExactKeys(value, ["hostId", "nonce", "scope", "generation"])) return null;
  const scope = toPreviewHostScope(value.scope);
  if (!isIdentifier(value.hostId) || !isSha256(value.nonce) || !scope || !isPositiveSafeInteger(value.generation)) return null;
  return { hostId: value.hostId, nonce: value.nonce, scope, generation: value.generation };
}

export function parsePreviewHostEvent(value: unknown): PreviewHostEvent | null {
  if (!isRecord(value) || !hasExactKeys(value, ["hostId", "nonce", "scope", "generation", "sequence", "event"])) return null;
  const descriptor = toPreviewHostDescriptor({ hostId: value.hostId, nonce: value.nonce, scope: value.scope, generation: value.generation });
  if (!descriptor || !isPositiveSafeInteger(value.sequence) || !isRecord(value.event) || typeof value.event.kind !== "string") return null;
  const event = value.event;
  if (event.kind === "ready" && hasExactKeys(event, ["kind"])) {
    return { ...descriptor, sequence: value.sequence, event: { kind: "ready" } };
  }
  if (event.kind === "console" && hasExactKeys(event, ["kind", "level", "message"]) &&
      (event.level === "log" || event.level === "info" || event.level === "warn" || event.level === "error") && isBoundedString(event.message, 1_024)) {
    return { ...descriptor, sequence: value.sequence, event: { kind: "console", level: event.level, message: event.message } };
  }
  if (event.kind === "runtime_error" && hasExactKeys(event, ["kind", "message"]) && isBoundedString(event.message, 1_024)) {
    return { ...descriptor, sequence: value.sequence, event: { kind: "runtime_error", message: event.message } };
  }
  if (event.kind === "interaction_event" && hasExactKeys(event, ["kind", "event_key", "payload_json"]) &&
      isIdentifier(event.event_key) && isSafeJsonObject(event.payload_json)) {
    return { ...descriptor, sequence: value.sequence, event: { kind: "interaction_event", event_key: event.event_key, payload_json: event.payload_json } };
  }
  return null;
}

function toPreviewHostScope(value: unknown): PreviewHostScope | null {
  if (!isRecord(value) || !hasExactKeys(value, ["artifactId", "sourceArtifactId", "sessionId", "artifactVersion", "languageId"]) ||
      !isIdentifier(value.artifactId) || !isIdentifier(value.sourceArtifactId) || !isIdentifier(value.sessionId) ||
      !isPositiveSafeInteger(value.artifactVersion) || !isIdentifier(value.languageId)) return null;
  return {
    artifactId: value.artifactId,
    sourceArtifactId: value.sourceArtifactId,
    sessionId: value.sessionId,
    artifactVersion: value.artifactVersion,
    languageId: value.languageId,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: string[]): boolean {
  const actual = Object.keys(value).sort();
  const sorted = [...expected].sort();
  return actual.length === sorted.length && actual.every((key, index) => key === sorted[index]);
}

function isIdentifier(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_.:-]{1,160}$/.test(value);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

function isPositiveSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isBoundedString(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && Array.from(value).length <= maximum;
}

function isSafeJsonObject(value: unknown): value is Readonly<Record<string, unknown>> {
  if (!isRecord(value) || !isSafeJsonValue(value, 0)) return false;
  try {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength <= 2_048;
  } catch {
    return false;
  }
}

function isSafeJsonValue(value: unknown, depth: number): boolean {
  if (depth > 6) return false;
  if (value === null || typeof value === "boolean" || typeof value === "string") return true;
  if (typeof value === "number") return Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER;
  if (Array.isArray(value)) return value.length <= 64 && value.every((item) => isSafeJsonValue(item, depth + 1));
  if (!isRecord(value)) return false;
  const entries = Object.entries(value);
  return entries.length <= 64 && entries.every(([key, item]) =>
    new TextEncoder().encode(key).byteLength >= 1
    && new TextEncoder().encode(key).byteLength <= 160
    && isSafeJsonValue(item, depth + 1));
}
