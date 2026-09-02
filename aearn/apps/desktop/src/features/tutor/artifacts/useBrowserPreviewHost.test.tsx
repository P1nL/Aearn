import { useRef } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { sha256TextAsync } from "../../../lib/sha256Async";
import {
  parsePreviewHostEvent,
  setPreviewHostApiForTests,
  type PreviewHostApi,
  type PreviewHostDescriptor,
  type PreviewHostEvent,
} from "./previewHostApi";
import { useBrowserPreviewHost } from "./useBrowserPreviewHost";

vi.mock("../../../lib/sha256Async", () => ({
  sha256TextAsync: vi.fn(async () => "a".repeat(64)),
}));

const scope = {
  artifactId: "artifact-1",
  sourceArtifactId: "artifact-1",
  sessionId: "session-1",
  artifactVersion: 1,
  languageId: "html_css",
};

function descriptor(generation = 1): PreviewHostDescriptor {
  return { hostId: "host-1", nonce: generation === 1 ? "a".repeat(64) : "b".repeat(64), scope, generation };
}

function bridgeEvent(event: PreviewHostEvent["event"], update: Partial<PreviewHostEvent> = {}): PreviewHostEvent {
  return { ...descriptor(), sequence: 1, event, ...update };
}

function Harness({ source }: { source: string }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const preview = useBrowserPreviewHost({ enabled: true, scope, source, containerRef: ref });
  return <section>
    <div ref={ref} />
    <span data-testid="status">{preview.status}</span>
    <span data-testid="error">{preview.errorCode}</span>
    <span data-testid="runtime">{preview.runtimeError}</span>
    <span data-testid="console">{preview.consoleItems.map((item) => item.message).join("|")}</span>
  </section>;
}

describe("useBrowserPreviewHost", () => {
  let listener: ((event: PreviewHostEvent) => void) | null;
  let api: PreviewHostApi;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(sha256TextAsync).mockReset().mockResolvedValue("a".repeat(64));
    vi.setSystemTime(new Date("2026-09-01T00:00:00Z"));
    listener = null;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      x: 12, y: 24, width: 420, height: 280, top: 24, right: 432, bottom: 304, left: 12,
      toJSON: () => ({}),
    });
    vi.stubGlobal("ResizeObserver", class {
      constructor(private readonly callback: ResizeObserverCallback) {}
      observe() { this.callback([], this as unknown as ResizeObserver); }
      disconnect() {}
      unobserve() {}
    });
    vi.stubGlobal("IntersectionObserver", class {
      readonly root = null;
      readonly rootMargin = "";
      readonly thresholds = [];
      constructor(private readonly callback: IntersectionObserverCallback) {}
      observe() { this.callback([], this as unknown as IntersectionObserver); }
      disconnect() {}
      unobserve() {}
      takeRecords() { return []; }
    });
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    api = {
      available: () => true,
      create: vi.fn(async () => descriptor()),
      updateSource: vi.fn(async () => descriptor(2)),
      setBounds: vi.fn(async () => undefined),
      recreate: vi.fn(async () => descriptor(2)),
      close: vi.fn(async () => undefined),
      listen: vi.fn(async (nextListener) => {
        listener = nextListener;
        return () => { listener = null; };
      }),
    };
    setPreviewHostApiForTests(api);
  });

  afterEach(() => {
    cleanup();
    setPreviewHostApiForTests(null);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("creates the native host, validates bridge identity, and tracks bounded console/runtime state", async () => {
    render(<Harness source="<button>ok</button>" />);
    await flushPromises();
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({
      scope,
      source: "<button>ok</button>",
      bounds: { x: 12, y: 24, width: 420, height: 280 },
      visible: true,
    }));
    expect(api.setBounds).toHaveBeenCalled();

    act(() => listener?.(bridgeEvent({ kind: "ready" })));
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
    act(() => listener?.(bridgeEvent({ kind: "runtime_error", message: "spoof" }, { nonce: "c".repeat(64) })));
    expect(screen.getByTestId("runtime")).toHaveTextContent("");
    act(() => listener?.(bridgeEvent({ kind: "console", level: "warn", message: "gap" }, { sequence: 3 })));
    expect(screen.getByTestId("console")).toHaveTextContent("");
    act(() => listener?.(bridgeEvent({ kind: "console", level: "warn", message: "safe log" }, { sequence: 2 })));
    act(() => listener?.(bridgeEvent({ kind: "runtime_error", message: "bounded runtime" }, { sequence: 3 })));
    act(() => listener?.(bridgeEvent({ kind: "console", level: "error", message: "replayed" }, { sequence: 2 })));
    expect(screen.getByTestId("console")).toHaveTextContent("safe log");
    expect(screen.getByTestId("console")).not.toHaveTextContent("replayed");
    expect(screen.getByTestId("runtime")).toHaveTextContent("bounded runtime");
  });

  it("debounces source updates and rotates to the returned nonce/generation", async () => {
    const rendered = render(<Harness source="first" />);
    await flushPromises();
    rendered.rerender(<Harness source="second" />);
    await act(async () => vi.advanceTimersByTime(399));
    expect(api.updateSource).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTime(1));
    await flushPromises();
    expect(api.updateSource).toHaveBeenCalledWith(expect.objectContaining({
      descriptor: descriptor(),
      source: "second",
      sourceHash: "a".repeat(64),
    }));
    act(() => listener?.(bridgeEvent({ kind: "ready" }, { ...descriptor(2), sequence: 1 })));
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
  });

  it("does not mix a newer draft with the hash captured for initial host creation", async () => {
    let resolveInitialHash: ((hash: string) => void) | null = null;
    vi.mocked(sha256TextAsync).mockImplementationOnce(() => new Promise((resolve) => {
      resolveInitialHash = resolve;
    }));
    const rendered = render(<Harness source="first" />);
    rendered.rerender(<Harness source="second" />);

    await act(async () => resolveInitialHash?.("a".repeat(64)));
    await flushPromises();
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ source: "first" }));

    await act(async () => vi.advanceTimersByTime(400));
    await flushPromises();
    expect(api.updateSource).toHaveBeenCalledWith(expect.objectContaining({ source: "second" }));
  });

  it("recreates only the preview host when the same-renderer ready heartbeat stops", async () => {
    render(<Harness source="while(true){}" />);
    await flushPromises();
    act(() => listener?.(bridgeEvent({ kind: "ready" })));
    await act(async () => vi.advanceTimersByTime(3_000));
    await flushPromises();
    expect(api.recreate).toHaveBeenCalledWith(descriptor());
    expect(screen.getByTestId("status")).toHaveTextContent("creating");

    await act(async () => vi.advanceTimersByTime(3_000));
    await flushPromises();
    expect(api.recreate).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("status")).toHaveTextContent("error");
    expect(screen.getByTestId("error")).toHaveTextContent("PREVIEW_HOST_UNRESPONSIVE");
    expect(api.setBounds).toHaveBeenCalledWith(expect.objectContaining({ visible: false }));
  });

  it("hides a failed source update and does not revive the stale host through the watchdog", async () => {
    vi.mocked(api.updateSource).mockRejectedValueOnce(new Error("update failed"));
    const rendered = render(<Harness source="first" />);
    await flushPromises();
    act(() => listener?.(bridgeEvent({ kind: "ready" })));
    rendered.rerender(<Harness source="second" />);

    await act(async () => vi.advanceTimersByTime(400));
    await flushPromises();
    expect(screen.getByTestId("status")).toHaveTextContent("error");
    expect(screen.getByTestId("error")).toHaveTextContent("PREVIEW_HOST_UPDATE_FAILED");
    expect(api.setBounds).toHaveBeenCalledWith(expect.objectContaining({ visible: false }));

    await act(async () => vi.advanceTimersByTime(4_000));
    expect(api.recreate).not.toHaveBeenCalled();
  });

  it("rejects malformed, oversized, and unsafe Preview interaction payloads before the hook sees them", () => {
    const base = {
      hostId: "host-1",
      nonce: "a".repeat(64),
      scope,
      generation: 1,
      sequence: 1,
      event: {
        kind: "interaction_event",
        event_key: "demo.click.completed",
        payload_json: { count: 1 },
      },
    };
    expect(parsePreviewHostEvent(base)).not.toBeNull();
    expect(parsePreviewHostEvent({ ...base, event: {
      ...base.event,
      payload_json: { nested: { one: { two: { three: { four: { five: { six: { seven: true } } } } } } } },
    } })).toBeNull();
    expect(parsePreviewHostEvent({ ...base, event: {
      ...base.event,
      payload_json: { message: "x".repeat(2_100) },
    } })).toBeNull();
    expect(parsePreviewHostEvent({ ...base, event: {
      ...base.event,
      payload_json: { count: Number.MAX_SAFE_INTEGER + 1 },
    } })).toBeNull();
  });

  it("closes only its native host on unmount", async () => {
    const rendered = render(<Harness source="safe" />);
    await flushPromises();
    rendered.unmount();
    expect(api.close).toHaveBeenCalledWith(descriptor());
  });
});

async function flushPromises(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}
