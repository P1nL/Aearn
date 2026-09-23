import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import { fetchLessonDocumentReference } from "../../../api";
import { getErrorInfo } from "../../../lib/errorMessages";
import type {
  LessonDocumentReferenceOpenRequest,
  LessonDocumentReferenceResolution,
} from "../../../types";
import { LessonBlockRenderer } from "./LessonBlockRenderer";
import { LessonSourcesPanel } from "./LessonSourcesPanel";

type DrawerState =
  | { status: "loading"; value: null; error: null }
  | { status: "ready"; value: LessonDocumentReferenceResolution; error: null }
  | { status: "error"; value: null; error: { code: string; message: string } };

type HighlightRect = { top: number; left: number; width: number; height: number };

export function LessonDocumentDrawer({
  userId,
  trackId,
  conversationId,
  request,
  onClose,
}: {
  userId: string;
  trackId: string;
  conversationId: string;
  request: LessonDocumentReferenceOpenRequest;
  onClose: () => void;
}) {
  const [state, setState] = useState<DrawerState>({ status: "loading", value: null, error: null });
  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(null);
  const [highlightRect, setHighlightRect] = useState<HighlightRect | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const loadControllerRef = useRef<AbortController | null>(null);
  const narrow = useNarrowDrawer();
  const requestKey = useMemo(() => JSON.stringify(request), [request]);
  const load = useCallback(() => {
    loadControllerRef.current?.abort();
    const controller = new AbortController();
    loadControllerRef.current = controller;
    setState({ status: "loading", value: null, error: null });
    void fetchLessonDocumentReference({
      userId,
      trackId,
      conversationId,
      knowledgeKey: request.knowledgeKey,
      source: request.source,
      signal: controller.signal,
    }).then((value) => {
      if (controller.signal.aborted) return;
      setSelectedCitationId(value.target.selected_citation_id ?? value.target.citation_ids[0] ?? null);
      setState({ status: "ready", value, error: null });
    }).catch((error) => {
      if (controller.signal.aborted) return;
      const info = getErrorInfo(error);
      setState({ status: "error", value: null, error: { code: info.code, message: info.message } });
    }).finally(() => {
      if (loadControllerRef.current === controller) loadControllerRef.current = null;
    });
  }, [conversationId, request.knowledgeKey, request.source, requestKey, trackId, userId]);

  useEffect(() => {
    load();
    return () => {
      loadControllerRef.current?.abort();
      loadControllerRef.current = null;
    };
  }, [load]);

  useEffect(() => {
    const frame = globalThis.requestAnimationFrame(() => closeRef.current?.focus({ preventScroll: true }));
    return () => globalThis.cancelAnimationFrame(frame);
  }, [requestKey]);

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    globalThis.document?.addEventListener("keydown", handleEscape);
    return () => globalThis.document?.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  useEffect(() => {
    const value = state.status === "ready" ? state.value : null;
    const scroll = scrollRef.current;
    const stage = stageRef.current;
    if (!value || !scroll || !stage) {
      setHighlightRect(null);
      return;
    }
    let secondFrame = 0;
    let didScroll = false;
    const locate = () => {
      const target = stage.querySelector<HTMLElement>('[data-document-drawer-block-id="' + cssEscape(value.target.block_id) + '"]');
      if (!target) {
        setHighlightRect(null);
        return;
      }
      setHighlightRect({
        top: target.offsetTop,
        left: target.offsetLeft,
        width: target.offsetWidth,
        height: target.offsetHeight,
      });
      if (!didScroll) {
        didScroll = true;
        const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
        scroll.scrollTo({ top: Math.max(0, target.offsetTop - 18), behavior: reduced ? "auto" : "smooth" });
      }
    };
    const frame = globalThis.requestAnimationFrame(() => {
      secondFrame = globalThis.requestAnimationFrame(locate);
    });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(locate);
    observer?.observe(stage);
    return () => {
      globalThis.cancelAnimationFrame(frame);
      if (secondFrame) globalThis.cancelAnimationFrame(secondFrame);
      observer?.disconnect();
    };
  }, [state]);

  function handleKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (!narrow || event.key !== "Tab" || !drawerRef.current) return;
    const focusable = [...drawerRef.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function selectCitation(citationId: string) {
    setSelectedCitationId(citationId);
    globalThis.requestAnimationFrame(() => {
      drawerRef.current?.querySelector<HTMLElement>('#document-drawer-source-' + cssEscape(citationId))
        ?.scrollIntoView({ behavior: "auto", block: "nearest" });
    });
  }

  const value = state.status === "ready" ? state.value : null;
  return <div className="lesson-document-drawer-layer" data-narrow={narrow || undefined}>
    <aside
      ref={drawerRef}
      className="lesson-document-drawer"
      role="dialog"
      aria-modal={narrow || undefined}
      aria-labelledby="lesson-document-drawer-title"
      onKeyDown={handleKeyDown}
    >
      <header className="lesson-document-drawer-header">
        <div>
          <p className="tutor-panel-eyebrow">Exact source</p>
          <h2 id="lesson-document-drawer-title">来源文档</h2>
        </div>
        <button ref={closeRef} className="tutor-text-button" type="button" onClick={onClose}>收起</button>
      </header>
      {state.status === "loading" ? <div className="lesson-document-drawer-status" role="status">正在加载引用时的文档版本…</div> : null}
      {state.status === "error" ? <div className="lesson-document-drawer-status error" role="alert">
        <strong>{state.error.code}</strong><span>{state.error.message}</span>
        <button className="tutor-text-button" type="button" onClick={load}>重试</button>
      </div> : null}
      {value ? <>
        {value.reference_status === "historical" ? <div className="lesson-document-version-notice" role="status">
          <strong>内容已更新</strong><span>正在显示该引用绑定的历史文档版本，不会定位到当前文档中的相似段落。</span>
        </div> : null}
        <div ref={scrollRef} className="lesson-document-drawer-scroll" tabIndex={0} aria-label="来源文档内容">
          <article className="lesson-document-drawer-document" aria-label={value.document.title}>
            <div className="lesson-document-drawer-meta">
              <span>版本 {value.assignment.assignment_version}</span>
              <span>{value.document.content_standard_version}</span>
            </div>
            <div ref={stageRef} className="lesson-document-drawer-stage">
              {value.document.blocks.map((block) => <div
                key={block.block_id}
                data-document-drawer-block-id={block.block_id}
              ><LessonBlockRenderer block={block} onCitation={(citationId) => selectCitation(citationId)} /></div>)}
              {highlightRect ? <div
                key={value.target.block_content_hash}
                className="lesson-document-drawer-highlight"
                aria-hidden="true"
                style={highlightRect}
              /> : null}
            </div>
          </article>
          <LessonSourcesPanel
            idPrefix="document-drawer"
            sources={value.sources}
            selectedCitationId={selectedCitationId}
            onSelect={selectCitation}
          />
        </div>
      </> : null}
    </aside>
  </div>;
}

function useNarrowDrawer(): boolean {
  const query = "(max-width: 767px)";
  const [matches, setMatches] = useState(() => globalThis.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const media = globalThis.matchMedia?.(query);
    if (!media) return;
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  return matches;
}

function cssEscape(value: string): string {
  return globalThis.CSS?.escape ? globalThis.CSS.escape(value) : value.replace(/["\\]/g, "\\$&");
}
