import { useEffect, useMemo, useRef, useState, type RefObject } from "react";

type ClockState = {
  resetKey: string;
  elapsedMs: number;
};

export function useDemonstrationVisibleClock(input: {
  enabled: boolean;
  current?: boolean;
  requiredMs: number;
  elementRef: RefObject<HTMLElement | null>;
  renderReady: boolean;
  resetKey: string;
}) {
  const [state, setState] = useState<ClockState>(() => ({ resetKey: input.resetKey, elapsedMs: 0 }));
  const [intersecting, setIntersecting] = useState(false);
  const [foreground, setForeground] = useState(documentIsForeground);
  const lastTickRef = useRef<number | null>(null);
  const elapsedMs = state.resetKey === input.resetKey ? state.elapsedMs : 0;
  const sessionId = useMemo(newClockSessionId, [input.resetKey]);

  useEffect(() => {
    lastTickRef.current = null;
    setState((current) => current.resetKey === input.resetKey
      ? current
      : { resetKey: input.resetKey, elapsedMs: 0 });
  }, [input.resetKey]);

  useEffect(() => {
    const element = input.elementRef.current;
    if (!element || typeof IntersectionObserver === "undefined") {
      setIntersecting(Boolean(element));
      return;
    }
    const observer = new IntersectionObserver(([entry]) => {
      setIntersecting(Boolean(entry?.isIntersecting && entry.intersectionRatio >= 0.6));
    }, { threshold: [0.6] });
    observer.observe(element);
    return () => observer.disconnect();
  }, [input.elementRef]);

  useEffect(() => {
    const update = () => setForeground(documentIsForeground());
    document.addEventListener("visibilitychange", update);
    window.addEventListener("focus", update);
    window.addEventListener("blur", update);
    return () => {
      document.removeEventListener("visibilitychange", update);
      window.removeEventListener("focus", update);
      window.removeEventListener("blur", update);
    };
  }, []);

  const counting = input.enabled
    && (input.current ?? true)
    && input.renderReady
    && foreground
    && intersecting
    && elapsedMs < input.requiredMs;

  useEffect(() => {
    if (!counting) {
      lastTickRef.current = null;
      return;
    }
    lastTickRef.current = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const previous = lastTickRef.current ?? now;
      lastTickRef.current = now;
      const delta = Math.max(0, now - previous);
      setState((current) => {
        if (current.resetKey !== input.resetKey) return { resetKey: input.resetKey, elapsedMs: 0 };
        return { ...current, elapsedMs: Math.min(input.requiredMs, current.elapsedMs + delta) };
      });
    }, 100);
    return () => window.clearInterval(timer);
  }, [counting, input.requiredMs, input.resetKey]);

  return {
    sessionId,
    elapsedMs,
    counting,
    complete: elapsedMs >= input.requiredMs,
    foreground,
    visible: intersecting,
    renderReady: input.renderReady,
  };
}

function documentIsForeground(): boolean {
  return document.visibilityState === "visible" && document.hasFocus();
}

function newClockSessionId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  return `clock-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}
