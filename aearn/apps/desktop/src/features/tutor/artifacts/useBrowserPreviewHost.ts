import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { sha256TextAsync } from "../../../lib/sha256Async";
import {
  previewHostApi,
  samePreviewScope,
  type PreviewHostBounds,
  type PreviewHostDescriptor,
  type PreviewHostEvent,
  type PreviewHostScope,
} from "./previewHostApi";

const SOURCE_DEBOUNCE_MS = 400;
const READY_TIMEOUT_MS = 2_800;
const WATCHDOG_INTERVAL_MS = 500;
const MAX_CONSOLE_ITEMS = 40;
const MAX_AUTOMATIC_RECREATES = 1;

export type PreviewConsoleItem = {
  id: string;
  level: "log" | "info" | "warn" | "error";
  message: string;
};

export type BrowserPreviewHostState = {
  status: "unavailable" | "creating" | "ready" | "recreating" | "error";
  errorCode: string | null;
  consoleItems: PreviewConsoleItem[];
  runtimeError: string | null;
  interactionEventKey: string | null;
  recreate: () => void;
};

export function useBrowserPreviewHost(input: {
  enabled: boolean;
  scope: PreviewHostScope;
  source: string;
  containerRef: RefObject<HTMLElement | null>;
}): BrowserPreviewHostState {
  const api = previewHostApi();
  const [descriptor, setDescriptor] = useState<PreviewHostDescriptor | null>(null);
  const [status, setStatus] = useState<BrowserPreviewHostState["status"]>(() => api.available() ? "creating" : "unavailable");
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [consoleItems, setConsoleItems] = useState<PreviewConsoleItem[]>([]);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [interactionEventKey, setInteractionEventKey] = useState<string | null>(null);
  const descriptorRef = useRef<PreviewHostDescriptor | null>(null);
  const sourceRef = useRef(input.source);
  const syncedSourceRef = useRef<string | null>(null);
  const lastReadyAtRef = useRef(0);
  const lastEventSequenceRef = useRef(0);
  const automaticRecreateCountRef = useRef(0);
  const recreatePendingRef = useRef(false);
  const lifecycleGenerationRef = useRef(0);
  sourceRef.current = input.source;
  descriptorRef.current = descriptor;

  const applyDescriptor = useCallback((next: PreviewHostDescriptor, nextStatus: BrowserPreviewHostState["status"]) => {
    descriptorRef.current = next;
    setDescriptor(next);
    lastReadyAtRef.current = Date.now();
    lastEventSequenceRef.current = 0;
    setStatus(nextStatus);
    setErrorCode(null);
  }, []);

  const hideHost = useCallback((target: PreviewHostDescriptor) => {
    void api.setBounds({
      descriptor: target,
      bounds: currentBounds(input.containerRef.current),
      visible: false,
    }).catch(() => undefined);
  }, [api, input.containerRef]);

  const recreateHost = useCallback((resetAutomaticBudget: boolean) => {
    const current = descriptorRef.current;
    if (!current || recreatePendingRef.current) return;
    if (resetAutomaticBudget) automaticRecreateCountRef.current = 0;
    recreatePendingRef.current = true;
    setStatus("recreating");
    setRuntimeError(null);
    void api.recreate(current).then((next) => {
      if (descriptorRef.current?.hostId !== current.hostId) return;
      applyDescriptor(next, "creating");
    }).catch(() => {
      if (descriptorRef.current?.hostId !== current.hostId) return;
      setStatus("error");
      setErrorCode("PREVIEW_HOST_RECREATE_FAILED");
    }).finally(() => {
      recreatePendingRef.current = false;
    });
  }, [api, applyDescriptor]);
  const recreate = useCallback(() => recreateHost(true), [recreateHost]);

  useEffect(() => {
    if (!input.enabled || !api.available()) {
      automaticRecreateCountRef.current = 0;
      setStatus("unavailable");
      setDescriptor(null);
      descriptorRef.current = null;
      return;
    }
    let active = true;
    const lifecycleGeneration = ++lifecycleGenerationRef.current;
    automaticRecreateCountRef.current = 0;
    setStatus("creating");
    setErrorCode(null);
    setConsoleItems([]);
    setRuntimeError(null);
    setInteractionEventKey(null);
    const sourceAtCreate = sourceRef.current;
    void sha256TextAsync(sourceAtCreate).then((sourceHash) => api.create({
      scope: input.scope,
      source: sourceAtCreate,
      sourceHash,
      bounds: currentBounds(input.containerRef.current),
      visible: isVisible(input.containerRef.current),
    })).then((created) => {
      if (!active || lifecycleGeneration !== lifecycleGenerationRef.current) {
        void api.close(created).catch(() => undefined);
        return;
      }
      syncedSourceRef.current = sourceAtCreate;
      applyDescriptor(created, "creating");
    }).catch(() => {
      if (!active) return;
      setStatus("error");
      setErrorCode("PREVIEW_HOST_CREATE_FAILED");
    });
    return () => {
      active = false;
      lifecycleGenerationRef.current += 1;
      const current = descriptorRef.current;
      descriptorRef.current = null;
      setDescriptor(null);
      syncedSourceRef.current = null;
      if (current) void api.close(current).catch(() => undefined);
    };
  }, [api, applyDescriptor, input.containerRef, input.enabled, input.scope.artifactId,
    input.scope.artifactVersion, input.scope.languageId, input.scope.sessionId, input.scope.sourceArtifactId]);

  useEffect(() => {
    if (!input.enabled || !api.available()) return;
    let active = true;
    let unlisten: (() => void) | null = null;
    void api.listen((event) => {
      if (!active || !matchesDescriptor(event, descriptorRef.current)
          || event.sequence <= lastEventSequenceRef.current) return;
      lastEventSequenceRef.current = event.sequence;
      if (event.event.kind === "ready") {
        lastReadyAtRef.current = Date.now();
        setStatus("ready");
        setErrorCode(null);
        return;
      }
      if (event.event.kind === "console") {
        const consoleEvent = event.event;
        setConsoleItems((current) => [...current, {
          id: `${event.generation}:${event.sequence}`,
          level: consoleEvent.level,
          message: consoleEvent.message,
        }].slice(-MAX_CONSOLE_ITEMS));
        return;
      }
      if (event.event.kind === "runtime_error") {
        setRuntimeError(event.event.message);
        return;
      }
      setInteractionEventKey(event.event.event_key);
    }).then((dispose) => {
      if (!active) dispose();
      else unlisten = dispose;
    }).catch(() => {
      if (active) {
        const current = descriptorRef.current;
        if (current) hideHost(current);
        setStatus("error");
        setErrorCode("PREVIEW_HOST_BRIDGE_UNAVAILABLE");
      }
    });
    return () => {
      active = false;
      unlisten?.();
    };
  }, [api, hideHost, input.enabled]);

  useEffect(() => {
    const current = descriptor;
    if (!current || syncedSourceRef.current === input.source) return;
    const timer = window.setTimeout(() => {
      const expected = descriptorRef.current;
      const desired = sourceRef.current;
      if (!expected || expected.hostId !== current.hostId || syncedSourceRef.current === desired) return;
      void sha256TextAsync(desired).then((sourceHash) => api.updateSource({
        descriptor: expected,
        source: desired,
        sourceHash,
      })).then((next) => {
        if (descriptorRef.current?.hostId !== expected.hostId) return;
        syncedSourceRef.current = desired;
        automaticRecreateCountRef.current = 0;
        setConsoleItems([]);
        setRuntimeError(null);
        setInteractionEventKey(null);
        applyDescriptor(next, "creating");
      }).catch(() => {
        if (descriptorRef.current?.hostId !== expected.hostId) return;
        hideHost(expected);
        setStatus("error");
        setErrorCode("PREVIEW_HOST_UPDATE_FAILED");
      });
    }, SOURCE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [api, applyDescriptor, descriptor, hideHost, input.source]);

  useEffect(() => {
    if (!descriptor || !input.containerRef.current) return;
    const element = input.containerRef.current;
    let frame = 0;
    const update = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        const current = descriptorRef.current;
        if (!current) return;
        void api.setBounds({
          descriptor: current,
          bounds: currentBounds(element),
          visible: isVisible(element),
        }).catch(() => undefined);
      });
    };
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    const intersectionObserver = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver(update);
    resizeObserver?.observe(element);
    intersectionObserver?.observe(element);
    document.addEventListener("scroll", update, { capture: true, passive: true });
    window.addEventListener("resize", update, { passive: true });
    update();
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      intersectionObserver?.disconnect();
      document.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [api, descriptor, input.containerRef]);

  useEffect(() => {
    if (!descriptor || status === "error" || status === "unavailable") return;
    const timer = window.setInterval(() => {
      if (Date.now() - lastReadyAtRef.current <= READY_TIMEOUT_MS) return;
      if (automaticRecreateCountRef.current >= MAX_AUTOMATIC_RECREATES) {
        const current = descriptorRef.current;
        if (current) hideHost(current);
        setStatus("error");
        setErrorCode("PREVIEW_HOST_UNRESPONSIVE");
        return;
      }
      automaticRecreateCountRef.current += 1;
      recreateHost(false);
    }, WATCHDOG_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [descriptor, hideHost, recreateHost, status]);

  return { status, errorCode, consoleItems, runtimeError, interactionEventKey, recreate };
}

function matchesDescriptor(event: PreviewHostEvent, descriptor: PreviewHostDescriptor | null): boolean {
  return descriptor !== null
    && event.hostId === descriptor.hostId
    && event.nonce === descriptor.nonce
    && event.generation === descriptor.generation
    && samePreviewScope(event.scope, descriptor.scope);
}

function currentBounds(element: HTMLElement | null): PreviewHostBounds {
  const rect = element?.getBoundingClientRect();
  return {
    x: rect?.x ?? 0,
    y: rect?.y ?? 0,
    width: Math.max(1, rect?.width ?? 1),
    height: Math.max(1, rect?.height ?? 1),
  };
}

function isVisible(element: HTMLElement | null): boolean {
  if (!element) return false;
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0
    && rect.top < window.innerHeight && rect.left < window.innerWidth;
}
