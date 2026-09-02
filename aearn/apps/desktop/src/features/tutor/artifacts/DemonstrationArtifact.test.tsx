import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TutorPublicArtifactItem } from "../../../types";
import { DemonstrationArtifact } from "./DemonstrationArtifact";

const previewHarness = vi.hoisted(() => ({
  props: null as null | {
    onReadyChange?: (ready: boolean) => void;
    onInteractionEvent?: (event: {
      eventKey: string;
      payloadJson: Readonly<Record<string, unknown>>;
      nonce: string;
      generation: number;
      sequence: number;
    }) => void;
  },
}));

vi.mock("./BrowserPreviewArtifact", () => ({
  BrowserPreviewSurface: (props: NonNullable<typeof previewHarness.props>) => {
    previewHarness.props = props;
    return <div data-testid="preview-surface" />;
  },
}));

const hash = "a".repeat(64);
let observerCallback: IntersectionObserverCallback | null = null;
let visibilityState: DocumentVisibilityState = "visible";
let focused = true;
let reducedMotion = false;
let nextClockId = 0;

function artifact(mode: "static" | "interactive", update: Partial<TutorPublicArtifactItem> = {}): TutorPublicArtifactItem {
  const interactive = mode === "interactive";
  return {
    kind: "artifact",
    id: "demo-1",
    conversation_id: "conversation-1",
    turn_id: "turn-1",
    learning_track_id: "track-1",
    knowledge_key: "javascript.dom",
    teaching_session_id: "session-1",
    checkpoint_id: "checkpoint-1",
    artifact_version: 1,
    artifact_kind: "demonstration",
    purpose: "demonstration",
    owner_kind: "learning_item",
    owner_id: "item-version-1",
    owner_version: 1,
    state: "active",
    blocking: true,
    title: "Published demonstration",
    instruction_markdown: "Observe the demonstration.",
    difficulty: "D1",
    presentation: {
      type: "demonstration_v2",
      descriptor_version: "demonstration_descriptor_v1",
      demonstration_mode: mode,
      source_version: "v2",
      language_id: "javascript",
      steps: [{
        step_key: "observe",
        title: "Observe",
        instruction_markdown: "Watch this exact interaction.",
        source_content: "<button>Run</button>",
        source_content_hash: hash,
        duration_seconds: interactive ? null : 6,
      }],
      expected_event: interactive ? {
        event_key: "demo.click.completed",
        payload_json: { count: 1 },
        payload_hash: "b".repeat(64),
      } : null,
      total_duration_seconds: interactive ? null : 6,
      completion_policy_version: "demonstration_completion_policy_v1",
    },
    allowed_actions: ["complete_demo", "cancel"],
    source_references: [],
    active_attempt: null,
    branch_summary: null,
    version: 1,
    created_at: "2026-09-02T00:00:00Z",
    updated_at: "2026-09-02T00:00:00Z",
    terminal_at: null,
    ...update,
  };
}

function observeVisible(ratio = 0.8): void {
  act(() => observerCallback?.([
    { isIntersecting: true, intersectionRatio: ratio } as IntersectionObserverEntry,
  ], {} as IntersectionObserver));
}

function dispatchVisibility(value: DocumentVisibilityState): void {
  visibilityState = value;
  act(() => document.dispatchEvent(new Event("visibilitychange")));
}

function dispatchFocus(value: boolean): void {
  focused = value;
  act(() => window.dispatchEvent(new Event(value ? "focus" : "blur")));
}

async function advance(milliseconds: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

describe("DemonstrationArtifact", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-02T00:00:00Z"));
    observerCallback = null;
    previewHarness.props = null;
    visibilityState = "visible";
    focused = true;
    reducedMotion = false;
    nextClockId = 0;
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibilityState,
    });
    vi.spyOn(document, "hasFocus").mockImplementation(() => focused);
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn(() => `clock-${++nextClockId}`),
    });
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: reducedMotion,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })));
    vi.stubGlobal("IntersectionObserver", class {
      readonly root = null;
      readonly rootMargin = "";
      readonly thresholds = [0.6];
      constructor(callback: IntersectionObserverCallback) { observerCallback = callback; }
      observe() {}
      disconnect() {}
      unobserve() {}
      takeRecords() { return []; }
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("counts only visible foreground time, pauses for visibility/focus, and submits one exact static receipt", async () => {
    const onAction = vi.fn().mockResolvedValue(undefined);
    render(<DemonstrationArtifact artifact={artifact("static")} onAction={onAction} />);
    await act(async () => {});

    await advance(1_000);
    expect(onAction).not.toHaveBeenCalled();
    observeVisible();
    await advance(2_000);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "33");

    dispatchVisibility("hidden");
    await advance(2_000);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "33");

    dispatchVisibility("visible");
    dispatchFocus(false);
    await advance(2_000);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "33");

    dispatchFocus(true);
    await advance(4_000);
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({
      action: "complete_demo",
      payload: {
        action: "complete_demo",
        evidence: expect.objectContaining({
          kind: "visible_clock",
          clock_session_id: "clock-1",
          visible_elapsed_ms: 6_000,
          foreground: true,
          current: true,
          visible: true,
          render_ready: true,
        }),
      },
    }));

    await advance(1_000);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("uses a fresh process-local clock after remount and switches progress to discrete reduced-motion steps", async () => {
    reducedMotion = true;
    const onAction = vi.fn().mockResolvedValue(undefined);
    const rendered = render(<DemonstrationArtifact artifact={artifact("static")} onAction={onAction} />);
    await act(async () => {});
    observeVisible();
    await advance(2_600);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");

    rendered.rerender(<DemonstrationArtifact artifact={artifact("static", { id: "demo-2", version: 2 })} onAction={onAction} />);
    await act(async () => {});
    observeVisible();
    await advance(3_500);
    expect(onAction).not.toHaveBeenCalled();
    await advance(2_500);
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({
      payload: expect.objectContaining({
        evidence: expect.objectContaining({ clock_session_id: "clock-2" }),
      }),
    }));
  });

  it("renders read-only code without editor, paste, or draft controls", () => {
    render(<DemonstrationArtifact artifact={artifact("static")} />);
    const code = screen.getByLabelText("Observe 只读代码");
    fireEvent.paste(code, { clipboardData: { getData: () => "mutated source" } });
    expect(code).toHaveTextContent("<button>Run</button>");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(code).not.toHaveAttribute("contenteditable");
  });

  it("accepts only the exact Preview event payload and forwards nonce/generation/sequence once", async () => {
    const onAction = vi.fn().mockResolvedValue(undefined);
    render(<DemonstrationArtifact artifact={artifact("interactive")} onAction={onAction} />);
    await act(async () => {});
    expect(previewHarness.props).not.toBeNull();

    act(() => previewHarness.props?.onReadyChange?.(true));
    act(() => previewHarness.props?.onInteractionEvent?.({
      eventKey: "demo.click.completed",
      payloadJson: { count: 2 },
      nonce: "c".repeat(64),
      generation: 2,
      sequence: 3,
    }));
    act(() => previewHarness.props?.onInteractionEvent?.({
      eventKey: "demo.other",
      payloadJson: { count: 1 },
      nonce: "c".repeat(64),
      generation: 2,
      sequence: 4,
    }));
    expect(onAction).not.toHaveBeenCalled();

    const event = {
      eventKey: "demo.click.completed",
      payloadJson: { count: 1 },
      nonce: "d".repeat(64),
      generation: 3,
      sequence: 5,
    };
    act(() => previewHarness.props?.onInteractionEvent?.(event));
    act(() => previewHarness.props?.onInteractionEvent?.(event));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({
      action: "complete_demo",
      payload: {
        action: "complete_demo",
        evidence: {
          kind: "interactive_event",
          event_key: "demo.click.completed",
          payload_json: { count: 1 },
          payload_hash: "b".repeat(64),
          preview_nonce: "d".repeat(64),
          preview_generation: 3,
          preview_sequence: 5,
        },
      },
    }));
  });
});
