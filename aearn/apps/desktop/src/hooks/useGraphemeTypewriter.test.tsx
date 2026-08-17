import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { splitGraphemes, useGraphemeTypewriter } from "./useGraphemeTypewriter";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useGraphemeTypewriter", () => {
  it("reveals exactly one grapheme per tick without splitting emoji", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useGraphemeTypewriter("A👨‍👩‍👧‍👦B", {
      animate: true,
      resetKey: "turn-1",
      intervalMs: 10,
    }));

    expect(result.current.text).toBe("");
    act(() => vi.advanceTimersByTime(10));
    expect(result.current.text).toBe("A");
    act(() => vi.advanceTimersByTime(10));
    expect(result.current.text).toBe("A👨‍👩‍👧‍👦");
    act(() => vi.advanceTimersByTime(10));
    expect(result.current.text).toBe("A👨‍👩‍👧‍👦B");
    expect(result.current.complete).toBe(true);
  });

  it("preserves newlines and resets the queue when the generation changes", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ target, resetKey }) => useGraphemeTypewriter(target, { animate: true, resetKey, intervalMs: 10 }),
      { initialProps: { target: "A\nB", resetKey: "generation-1" } },
    );

    act(() => vi.advanceTimersByTime(10));
    act(() => vi.advanceTimersByTime(10));
    expect(result.current.text).toBe("A\n");
    rerender({ target: "XY", resetKey: "generation-2" });
    expect(result.current.text).toBe("");
    act(() => vi.advanceTimersByTime(10));
    expect(result.current.text).toBe("X");
  });

  it("synchronizes approved text immediately for reduced motion", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: true,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));

    const { result } = renderHook(() => useGraphemeTypewriter("直接显示", {
      animate: true,
      resetKey: "reduced",
      intervalMs: 10,
    }));

    expect(result.current.reducedMotion).toBe(true);
    expect(result.current.text).toBe("直接显示");
    expect(result.current.complete).toBe(true);
  });

  it("cleans up its pending timer on unmount", () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useGraphemeTypewriter("尚未完成", {
      animate: true,
      resetKey: "cleanup",
      intervalMs: 100,
    }));
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("exposes the same grapheme segmentation used by the queue", () => {
    expect(splitGraphemes("é🙂")).toEqual(["é", "🙂"]);
  });
});
