import { useEffect, useMemo, useState } from "react";

export type GraphemeTypewriterOptions = {
  animate: boolean;
  initialText?: string;
  resetKey: string;
  intervalMs?: number;
};

export type GraphemeTypewriterState = {
  text: string;
  complete: boolean;
  reducedMotion: boolean;
};

export function splitGraphemes(value: string): string[] {
  if (typeof Intl !== "undefined" && "Segmenter" in Intl) {
    const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });
    return Array.from(segmenter.segment(value), (item) => item.segment);
  }
  return Array.from(value);
}

export function useGraphemeTypewriter(
  targetText: string,
  { animate, initialText = "", resetKey, intervalMs = 18 }: GraphemeTypewriterOptions,
): GraphemeTypewriterState {
  const reducedMotion = usePrefersReducedMotion();
  const [text, setText] = useState(() => boundedInitialText(targetText, initialText));
  const targetGraphemes = useMemo(() => splitGraphemes(targetText), [targetText]);

  useEffect(() => {
    setText(boundedInitialText(targetText, initialText));
  }, [initialText, resetKey]);

  useEffect(() => {
    if (!animate || reducedMotion) {
      setText(targetText);
      return;
    }
    if (!targetText.startsWith(text)) {
      setText("");
      return;
    }
    const displayedCount = splitGraphemes(text).length;
    if (displayedCount >= targetGraphemes.length) return;
    const timer = window.setTimeout(() => {
      setText(targetGraphemes.slice(0, displayedCount + 1).join(""));
    }, intervalMs);
    return () => window.clearTimeout(timer);
  }, [animate, intervalMs, reducedMotion, targetGraphemes, targetText, text]);

  return { text, complete: text === targetText, reducedMotion };
}

function boundedInitialText(targetText: string, initialText: string): string {
  return initialText && targetText.startsWith(initialText) ? initialText : "";
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  return reduced;
}
