import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { TutorArtifactAction, TutorPublicArtifactItem } from "../../../types";
import type { TutorArtifactActionHandler } from "./artifactRendererTypes";
import { BrowserPreviewSurface } from "./BrowserPreviewArtifact";
import { SafeMarkdown } from "./SafeMarkdown";
import { useDemonstrationVisibleClock } from "./useDemonstrationVisibleClock";

export function DemonstrationArtifact({
  artifact,
  onAction,
  actionBusy = false,
}: {
  artifact: TutorPublicArtifactItem;
  onAction?: TutorArtifactActionHandler;
  actionBusy?: boolean;
}) {
  const presentation = artifact.presentation;
  if (presentation.type === "demonstration_v1") return <LegacyDemonstration artifact={artifact} />;
  if (presentation.type !== "demonstration_v2") {
    return <div className="inline-artifact-contract-error" role="alert">ARTIFACT_PRESENTATION_CONTRACT_ERROR</div>;
  }
  return <DemonstrationV2
    key={artifact.id + ":" + artifact.version}
    artifact={artifact}
    onAction={onAction}
    actionBusy={actionBusy}
  />;
}

function DemonstrationV2({
  artifact,
  onAction,
  actionBusy,
}: {
  artifact: TutorPublicArtifactItem;
  onAction?: TutorArtifactActionHandler;
  actionBusy: boolean;
}) {
  const presentation = artifact.presentation;
  if (presentation.type !== "demonstration_v2") {
    return <div className="inline-artifact-contract-error" role="alert">ARTIFACT_PRESENTATION_CONTRACT_ERROR</div>;
  }

  const [submitting, setSubmitting] = useState(false);
  const [previewReady, setPreviewReady] = useState(false);
  const [renderReady, setRenderReady] = useState(false);
  const shellRef = useRef<HTMLElement | null>(null);
  const completionStartedRef = useRef(false);
  const requiredMs = (presentation.total_duration_seconds ?? 0) * 1_000;
  const canComplete = artifact.allowed_actions.includes("complete_demo");
  const current = artifact.state === "ready" || artifact.state === "active" || artifact.state === "running";
  const clock = useDemonstrationVisibleClock({
    enabled: presentation.demonstration_mode === "static" && canComplete,
    current,
    requiredMs,
    elementRef: shellRef,
    renderReady,
    resetKey: artifact.id + ":" + artifact.version,
  });
  const reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const rawProgress = requiredMs > 0 ? Math.min(1, clock.elapsedMs / requiredMs) : 0;
  const visibleProgress = reducedMotion ? Math.floor(rawProgress * 4) / 4 : rawProgress;
  const expectedJson = useMemo(
    () => canonicalJson(presentation.expected_event?.payload_json ?? {}),
    [presentation.expected_event],
  );

  useEffect(() => {
    setRenderReady(true);
  }, []);

  const complete = useCallback(async (payload: TutorArtifactAction) => {
    if (!onAction || completionStartedRef.current || actionBusy || !canComplete) return;
    completionStartedRef.current = true;
    setSubmitting(true);
    try {
      await onAction({ artifact, action: "complete_demo", payload });
    } catch {
      completionStartedRef.current = false;
    } finally {
      setSubmitting(false);
    }
  }, [actionBusy, artifact, canComplete, onAction]);

  useEffect(() => {
    if (!clock.complete || presentation.demonstration_mode !== "static") return;
    void complete({
      action: "complete_demo",
      evidence: {
        kind: "visible_clock",
        clock_session_id: clock.sessionId,
        visible_elapsed_ms: Math.round(clock.elapsedMs),
        foreground: true,
        current: true,
        visible: true,
        render_ready: true,
      },
    });
  }, [clock.complete, clock.elapsedMs, clock.sessionId, complete, presentation.demonstration_mode]);

  return <section className={"demonstration-artifact mode-" + presentation.demonstration_mode} ref={shellRef} aria-label="教学演示">
    <div className="demonstration-steps">
      {presentation.steps.map((step) => <article key={step.step_key} className="demonstration-step">
        <header><strong>{step.title}</strong>{step.duration_seconds ? <span>{step.duration_seconds}s</span> : null}</header>
        <SafeMarkdown markdown={step.instruction_markdown} surface="artifact" />
        <pre className="demonstration-code" aria-label={step.title + " 只读代码"}><code>{step.source_content}</code></pre>
        {presentation.demonstration_mode === "interactive" ? <BrowserPreviewSurface
          artifactId={artifact.id}
          sourceArtifactId={artifact.id}
          sessionId={artifact.teaching_session_id}
          artifactVersion={artifact.version}
          languageId={presentation.language_id}
          source={step.source_content}
          enabled
          ariaLabel="教学演示隔离预览"
          onReadyChange={setPreviewReady}
          onInteractionEvent={(event) => {
            const expected = presentation.expected_event;
            if (!previewReady || !expected || event.eventKey !== expected.event_key || canonicalJson(event.payloadJson) !== expectedJson) return;
            void complete({
              action: "complete_demo",
              evidence: {
                kind: "interactive_event",
                event_key: event.eventKey,
                payload_json: event.payloadJson,
                payload_hash: expected.payload_hash,
                preview_nonce: event.nonce,
                preview_generation: event.generation,
                preview_sequence: event.sequence,
              },
            });
          }}
        /> : null}
      </article>)}
    </div>
    {presentation.demonstration_mode === "static" ? <div
      className="demonstration-progress"
      aria-label="演示观看进度"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(visibleProgress * 100)}
      role="progressbar"
    ><span style={{ width: String(visibleProgress * 100) + "%" }} /></div> : null}
    {submitting || actionBusy ? <span className="demonstration-completing" role="status">正在确认演示完成…</span> : null}
  </section>;
}

function LegacyDemonstration({ artifact }: { artifact: TutorPublicArtifactItem }) {
  const presentation = artifact.presentation;
  if (presentation.type !== "demonstration_v1") return null;
  return <section className="demonstration-artifact legacy" aria-label="教学演示">
    <pre className="demonstration-code"><code>{presentation.source_content}</code></pre>
    <small>旧版演示只读展示，不自动完成。</small>
  </section>;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return "{" + Object.keys(record).sort().map((key) => JSON.stringify(key) + ":" + canonicalJson(record[key])).join(",") + "}";
  }
  return JSON.stringify(value);
}
