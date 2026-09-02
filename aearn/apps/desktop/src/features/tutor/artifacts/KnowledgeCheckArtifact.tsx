import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";

import type { TutorArtifactResponse, TutorPublicArtifactItem } from "../../../types";
import { Button } from "../../../ui/dsh-derived";
import { SafeMarkdown } from "./SafeMarkdown";
import type { TutorArtifactActionHandler } from "./artifactRendererTypes";

type KnowledgePresentation = Extract<
  TutorPublicArtifactItem["presentation"],
  { type: "knowledge_check_v1" }
>;

type OverlayPosition = Pick<CSSProperties, "left" | "top" | "width" | "maxHeight">;

export function KnowledgeCheckArtifact({ artifact, onAction, actionBusy = false }: {
  artifact: TutorPublicArtifactItem;
  onAction?: TutorArtifactActionHandler;
  actionBusy?: boolean;
}) {
  const presentation = artifact.presentation;
  if (presentation.type !== "knowledge_check_v1") return null;
  return <KnowledgeCheckArtifactContent artifact={artifact} presentation={presentation} onAction={onAction} actionBusy={actionBusy} />;
}

function KnowledgeCheckArtifactContent({ artifact, presentation, onAction, actionBusy }: {
  artifact: TutorPublicArtifactItem;
  presentation: KnowledgePresentation;
  onAction?: TutorArtifactActionHandler;
  actionBusy: boolean;
}) {
  const hints = presentation.hints ?? [];
  const revealedHintLevels = presentation.revealed_hint_levels ?? [];
  const [selected, setSelected] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [ordering, setOrdering] = useState(() => presentation.options.map((item) => item.value));
  const [startLine, setStartLine] = useState(1);
  const [endLine, setEndLine] = useState(1);
  const [category, setCategory] = useState("");
  const [note, setNote] = useState("");
  const [hintOpen, setHintOpen] = useState(false);
  const [hintIndex, setHintIndex] = useState(Math.max(0, revealedHintLevels.length - 1));
  const [overlayPosition, setOverlayPosition] = useState<OverlayPosition>({ left: 12, top: 12, width: 420, maxHeight: 520 });
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const hintTriggerRef = useRef<HTMLButtonElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const previousRevealedCountRef = useRef(revealedHintLevels.length);
  const locked = presentation.answer_locked ?? false;
  const revealedHints = hints.slice(0, revealedHintLevels.length);
  const canRevealNext = !locked
    && revealedHintLevels.length < hints.length
    && artifact.allowed_actions.includes("request_hint");
  const canRequestDirectAnswer = !locked && artifact.allowed_actions.includes("request_direct_answer");
  const response = buildResponse({ presentation, selected, text, ordering, startLine, endLine, category, note });

  useEffect(() => {
    setOrdering(presentation.options.map((item) => item.value));
  }, [artifact.id, presentation.response_kind, presentation.options]);

  useEffect(() => {
    const previousCount = previousRevealedCountRef.current;
    previousRevealedCountRef.current = revealedHintLevels.length;
    if (hintOpen && revealedHintLevels.length > previousCount) {
      setHintIndex(revealedHintLevels.length - 1);
    } else if (hintIndex >= revealedHintLevels.length && revealedHintLevels.length > 0) {
      setHintIndex(revealedHintLevels.length - 1);
    }
  }, [hintIndex, hintOpen, revealedHintLevels.length]);

  useLayoutEffect(() => {
    if (!hintOpen) return;
    const position = () => setOverlayPosition(positionOverlay(hintTriggerRef.current));
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [hintOpen]);

  useEffect(() => {
    if (!hintOpen) return;
    overlayRef.current?.focus();
    const onWindowKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeHints();
    };
    window.addEventListener("keydown", onWindowKeyDown);
    return () => window.removeEventListener("keydown", onWindowKeyDown);
  }, [hintOpen]);

  function openHints(targetIndex = Math.max(0, revealedHintLevels.length - 1)) {
    if (!hintOpen) {
      const active = document.activeElement;
      returnFocusRef.current = active instanceof HTMLElement && active !== document.body
        ? active
        : hintTriggerRef.current;
    }
    setHintIndex(targetIndex);
    setHintOpen(true);
    requestAnimationFrame(() => overlayRef.current?.focus());
  }

  function closeHints() {
    setHintOpen(false);
    const target = returnFocusRef.current?.isConnected
      ? returnFocusRef.current
      : hintTriggerRef.current;
    requestAnimationFrame(() => target?.focus());
  }

  async function revealNextHint() {
    const level = revealedHintLevels.length + 1;
    let targetIndex = Math.max(0, revealedHintLevels.length - 1);
    const updated = await onAction?.({
      artifact,
      action: "request_hint",
      payload: { action: "request_hint", hint_level: level },
    });
    if (updated && updated.presentation.type === "knowledge_check_v1") {
      const count = (updated.presentation.revealed_hint_levels ?? []).length;
      targetIndex = Math.max(0, count - 1);
    }
    openHints(targetIndex);
  }

  function toggle(value: string) {
    if (presentation.response_kind === "single_select") {
      setSelected([value]);
      return;
    }
    setSelected((current) => {
      if (current.includes(value)) return current.filter((item) => item !== value);
      if (current.length >= presentation.maximum_selections) return current;
      return [...current, value];
    });
  }

  function moveOrdering(index: number, direction: -1 | 1) {
    setOrdering((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  return <section className="knowledge-check-artifact" aria-label="结构化检查">
    <SafeMarkdown markdown={presentation.prompt_markdown} surface="artifact" />
    {!locked && (presentation.response_kind === "single_select" || presentation.response_kind === "multi_select")
      ? <fieldset className="knowledge-check-options" disabled={actionBusy}>
          <legend className="sr-only">请选择答案</legend>
          {presentation.options.map((option) => <label key={option.value}>
            <input
              aria-label={option.label}
              type={presentation.response_kind === "single_select" ? "radio" : "checkbox"}
              name={`knowledge-check-${artifact.id}`}
              checked={selected.includes(option.value)}
              onChange={() => toggle(option.value)}
            />
            <span>{option.label}</span>
          </label>)}
        </fieldset>
      : null}
    {!locked && presentation.response_kind === "ordering"
      ? <ol className="knowledge-check-ordering" aria-label="排序答案">
          {ordering.map((value, index) => {
            const option = presentation.options.find((item) => item.value === value);
            return <li key={value}>
              <span>{option?.label ?? value}</span>
              <span className="knowledge-check-ordering-actions">
                <Button variant="outline" disabled={actionBusy || index === 0} onClick={() => moveOrdering(index, -1)} aria-label={`上移 ${option?.label ?? value}`}>↑</Button>
                <Button variant="outline" disabled={actionBusy || index === ordering.length - 1} onClick={() => moveOrdering(index, 1)} aria-label={`下移 ${option?.label ?? value}`}>↓</Button>
              </span>
            </li>;
          })}
        </ol>
      : null}
    {!locked && (presentation.response_kind === "short_text" || presentation.response_kind === "prediction")
      ? <textarea
          aria-label={presentation.response_kind === "prediction" ? "预测答案" : "回答"}
          value={text}
          maxLength={presentation.maximum_text_length}
          disabled={actionBusy}
          onChange={(event) => setText(event.currentTarget.value)}
        />
      : null}
    {!locked && presentation.response_kind === "code_range"
      ? <fieldset className="knowledge-check-code-range" disabled={actionBusy}>
          <legend className="sr-only">代码范围答案</legend>
          <label>起始行<input aria-label="起始行" type="number" min={1} max={4000} value={startLine} onChange={(event) => setStartLine(Number(event.currentTarget.value))} /></label>
          <label>结束行<input aria-label="结束行" type="number" min={1} max={4000} value={endLine} onChange={(event) => setEndLine(Number(event.currentTarget.value))} /></label>
          <label>问题类别<input aria-label="问题类别" value={category} maxLength={160} onChange={(event) => setCategory(event.currentTarget.value)} /></label>
          <label className="knowledge-check-code-range-note">说明<textarea aria-label="范围说明" value={note} maxLength={2000} onChange={(event) => setNote(event.currentTarget.value)} /></label>
        </fieldset>
      : null}
    {locked ? <section className={`knowledge-check-outcome ${presentation.outcome}`} aria-live="polite">
      <strong>{presentation.outcome === "correct" ? "回答正确" : presentation.assistance_kind === "direct_answer" ? "已查看答案" : "需要补救"}</strong>
      <SafeMarkdown markdown={presentation.evaluation_markdown ?? ""} surface="artifact" />
    </section> : <div className="knowledge-check-actions">
      {(revealedHints.length > 0 || canRevealNext) ? <Button ref={hintTriggerRef} variant="outline" disabled={actionBusy || !onAction} onClick={() => {
        if (revealedHints.length > 0) openHints();
        else void revealNextHint();
      }}>提示</Button> : null}
      {canRequestDirectAnswer ? <Button variant="outline" disabled={actionBusy || !onAction} onClick={() => {
        void onAction?.({ artifact, action: "request_direct_answer", payload: { action: "request_direct_answer" } });
      }}>查看答案</Button> : null}
      <Button variant="primary" busy={actionBusy} disabled={!onAction || actionBusy || response === null} onClick={() => {
        if (response) void onAction?.({ artifact, action: "respond", payload: { action: "respond", response } });
      }}>提交回答</Button>
    </div>}
    {hintOpen && revealedHints.length > 0 ? createPortal(
      <div className="knowledge-check-hint-layer" data-testid="knowledge-check-hint-layer">
        <div
          className="knowledge-check-hint-overlay"
          role="dialog"
          aria-modal="false"
          aria-label="分级提示"
          aria-describedby={`knowledge-check-hint-page-${artifact.id}-${hintIndex + 1}`}
          tabIndex={-1}
          ref={overlayRef}
          style={overlayPosition}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              closeHints();
            } else if (event.key === "ArrowLeft") {
              event.preventDefault();
              setHintIndex((value) => Math.max(0, value - 1));
            } else if (event.key === "ArrowRight") {
              event.preventDefault();
              setHintIndex((value) => Math.min(revealedHints.length - 1, value + 1));
            } else if (event.key === "Home") {
              event.preventDefault();
              setHintIndex(0);
            } else if (event.key === "End") {
              event.preventDefault();
              setHintIndex(revealedHints.length - 1);
            }
          }}
        >
          <header><strong>H{hintIndex + 1} · {revealedHints[hintIndex]?.label}</strong><button type="button" aria-label="关闭提示" onClick={closeHints}>×</button></header>
          <div className="knowledge-check-hint-pages" style={{ transform: `translateX(-${hintIndex * 100}%)` }}>
            {revealedHints.map((hint, index) => <section
              id={`knowledge-check-hint-page-${artifact.id}-${hint.level}`}
              key={hint.level}
              aria-label={`H${hint.level} ${hint.label}`}
              aria-hidden={index !== hintIndex}
              inert={index !== hintIndex}
            ><SafeMarkdown markdown={hint.markdown} surface="artifact" /></section>)}
          </div>
          <footer>
            <Button variant="outline" disabled={hintIndex === 0} onClick={() => setHintIndex((value) => Math.max(0, value - 1))}>上一页</Button>
            <span aria-live="polite">{hintIndex + 1} / {revealedHints.length}</span>
            {hintIndex < revealedHints.length - 1
              ? <Button variant="outline" onClick={() => setHintIndex((value) => value + 1)}>下一页</Button>
              : canRevealNext ? <Button variant="outline" busy={actionBusy} disabled={!onAction || actionBusy} onClick={() => void revealNextHint()}>查看 H{revealedHintLevels.length + 1}</Button> : <span />}
          </footer>
        </div>
      </div>,
      document.body,
    ) : null}
  </section>;
}

function positionOverlay(anchor: HTMLElement | null): OverlayPosition {
  const viewportWidth = Math.max(320, window.innerWidth);
  const viewportHeight = Math.max(320, window.innerHeight);
  const width = Math.min(440, viewportWidth - 24);
  if (!anchor || viewportWidth <= 720) {
    return { left: 12, top: Math.max(12, viewportHeight - Math.min(560, viewportHeight * 0.72) - 12), width, maxHeight: Math.min(560, viewportHeight - 24) };
  }
  const rect = anchor.getBoundingClientRect();
  const left = Math.min(Math.max(12, rect.left), viewportWidth - width - 12);
  const estimatedHeight = Math.min(420, viewportHeight - 24);
  const below = rect.bottom + 8;
  const top = below + estimatedHeight <= viewportHeight - 12
    ? below
    : Math.max(12, rect.top - estimatedHeight - 8);
  return { left, top, width, maxHeight: Math.min(560, viewportHeight - top - 12) };
}

function buildResponse(input: {
  presentation: KnowledgePresentation;
  selected: string[];
  text: string;
  ordering: string[];
  startLine: number;
  endLine: number;
  category: string;
  note: string;
}): TutorArtifactResponse | null {
  const { presentation } = input;
  if (presentation.response_kind === "single_select") {
    return input.selected.length === 1 ? { kind: "single_select", value: input.selected[0] } : null;
  }
  if (presentation.response_kind === "multi_select") {
    return input.selected.length >= presentation.minimum_selections
      && input.selected.length <= presentation.maximum_selections
      ? { kind: "multi_select", values: input.selected }
      : null;
  }
  if (presentation.response_kind === "ordering") {
    return input.ordering.length === presentation.options.length
      && new Set(input.ordering).size === input.ordering.length
      ? { kind: "ordering", values: input.ordering }
      : null;
  }
  if (presentation.response_kind === "short_text" || presentation.response_kind === "prediction") {
    const value = input.text.trim();
    return value && value.length <= presentation.maximum_text_length
      ? { kind: presentation.response_kind, text: value }
      : null;
  }
  if (presentation.response_kind === "code_range") {
    const normalizedCategory = input.category.trim().toLowerCase();
    const normalizedNote = input.note.trim();
    return Number.isInteger(input.startLine)
      && Number.isInteger(input.endLine)
      && input.startLine >= 1
      && input.endLine >= input.startLine
      && input.endLine <= 4000
      && /^[a-z0-9][a-z0-9._:-]{0,159}$/.test(normalizedCategory)
      && normalizedNote.length > 0
      ? {
          kind: "code_range",
          start_line: input.startLine,
          end_line: input.endLine,
          category: normalizedCategory,
          note: normalizedNote,
        }
      : null;
  }
  return null;
}
