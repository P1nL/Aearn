import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import type { LessonAssignment, LessonBlock, LessonCitation, LessonDocument, LessonExerciseGateBlock, LessonSelectionReferenceDraft, LessonFollowTarget } from "../../../types";
import { LessonBlockRenderer } from "./LessonBlockRenderer";
import { LessonSourcesPanel } from "./LessonSourcesPanel";

type LessonDocumentViewProps = {
  document: LessonDocument;
  assignment: LessonAssignment;
  sources: LessonCitation[];
  renderExerciseGate?: (block: LessonExerciseGateBlock) => ReactNode;
  onSelectionReference?: (draft: LessonSelectionReferenceDraft, label: string) => void;
  learningTrackId?: string;
  followTarget?: LessonFollowTarget | null;
  followEnabled?: boolean;
  onFollowPause?: () => void;
  onFollowConflict?: (message: string | null) => void;
};

type SelectionCandidate = {
  blockId: string;
  startOffset: number;
  endOffset: number;
  excerpt: string;
};

export function LessonDocumentView({ document, assignment, sources, renderExerciseGate, onSelectionReference, learningTrackId, followTarget = null, followEnabled = false, onFollowPause, onFollowConflict }: LessonDocumentViewProps) {
  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(sources[0]?.citation_id ?? null);
  const [selectionCandidate, setSelectionCandidate] = useState<SelectionCandidate | null>(null);
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null);
  const programmaticFollowRef = useRef(false);

  useEffect(() => {
    if (!followEnabled || !followTarget) return;
    if (followTarget.document_id !== assignment.document_id || followTarget.document_content_hash !== document.content_hash) {
      onFollowConflict?.("当前讲解目标不属于 active frozen LessonDocument，已停止自动定位。");
      return;
    }
    const target = globalThis.document?.querySelector<HTMLElement>(`[data-lesson-block-id="${cssEscape(followTarget.block_id)}"]`) ?? null;
    if (!target) {
      onFollowConflict?.("当前讲解对应的课程块不存在，已停止自动定位。");
      return;
    }
    onFollowConflict?.(null);
    programmaticFollowRef.current = true;
    const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    let releaseFrame = 0;
    const frame = globalThis.requestAnimationFrame(() => {
      target.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
      releaseFrame = globalThis.requestAnimationFrame(() => { programmaticFollowRef.current = false; });
    });
    return () => { globalThis.cancelAnimationFrame(frame); if (releaseFrame) globalThis.cancelAnimationFrame(releaseFrame); };
  }, [assignment.document_id, document.content_hash, followEnabled, followTarget, onFollowConflict]);

  function pauseFollow() {
    if (!programmaticFollowRef.current) onFollowPause?.();
  }

  function handleReadingKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) pauseFollow();
  }

  function focusCitation(citationId: string) {
    setSelectedCitationId(citationId);
    const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    globalThis.requestAnimationFrame(() => documentRef(citationId)?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest" }));
  }

  function captureSelection(event: MouseEvent<HTMLElement>) {
    pauseFollow();
    if (!onSelectionReference || !learningTrackId) return;
    const selection = globalThis.getSelection?.();
    const excerpt = normalizeSelection(selection?.toString() ?? "");
    if (!selection || selection.isCollapsed || !excerpt) {
      setSelectionCandidate(null);
      setSelectionMessage(null);
      return;
    }
    if (excerpt.length > 800) {
      setSelectionCandidate(null);
      setSelectionMessage("单条课程引用最多选择 800 个字符。");
      return;
    }
    const target = event.target instanceof Element ? event.target : null;
    const blockElement = target?.closest<HTMLElement>("[data-lesson-block-id]") ?? null;
    const blockId = blockElement?.dataset.lessonBlockId ?? null;
    const block = blockId ? document.blocks.find((item) => item.block_id === blockId) : null;
    if (!block || !selectionWithinElement(selection, blockElement)) {
      setSelectionCandidate(null);
      setSelectionMessage("请只选择同一个课程块中的文本或代码。");
      return;
    }
    const canonical = normalizeSelection(lessonBlockPublicText(block));
    const startOffset = canonical.indexOf(excerpt);
    if (startOffset < 0 || canonical.lastIndexOf(excerpt) !== startOffset) {
      setSelectionCandidate(null);
      setSelectionMessage("当前选择无法唯一映射到 frozen 课程块，请缩小选择范围后重试。");
      return;
    }
    setSelectionCandidate({ blockId: block.block_id, startOffset, endOffset: startOffset + excerpt.length, excerpt });
    setSelectionMessage(null);
  }

  function addSelectionReference() {
    if (!selectionCandidate || !onSelectionReference || !learningTrackId) return;
    onSelectionReference({
      kind: "lesson_selection",
      learning_track_id: learningTrackId,
      knowledge_key: document.knowledge_key,
      document_id: assignment.document_id,
      document_content_hash: document.content_hash,
      block_id: selectionCandidate.blockId,
      start_offset: selectionCandidate.startOffset,
      end_offset: selectionCandidate.endOffset,
      excerpt: selectionCandidate.excerpt,
    }, `课程选段 · ${selectionCandidate.excerpt.slice(0, 42)}${selectionCandidate.excerpt.length > 42 ? "…" : ""}`);
    globalThis.getSelection?.()?.removeAllRanges();
    setSelectionCandidate(null);
    setSelectionMessage("已加入 Tutor 引用草稿。");
  }

  return (
    <div className="lesson-reading-layout" onWheelCapture={pauseFollow} onTouchStartCapture={pauseFollow} onPointerDownCapture={pauseFollow} onKeyDownCapture={handleReadingKeyDown}>
      <article className="lesson-document" aria-label={document.title} onMouseUp={captureSelection}>
        <div className="lesson-document-meta"><span>版本 {assignment.assignment_version}</span><span>{assignment.started_at ? "已开始 · 内容已冻结" : "尚未开始 · 可冻结当前版本"}</span><span>{document.content_standard_version}</span></div>
        {onSelectionReference && learningTrackId ? (
          <div className={`lesson-selection-reference${selectionCandidate ? " ready" : ""}`} aria-live="polite">
            {selectionCandidate ? <><span><strong>引用所选内容</strong><small>{selectionCandidate.excerpt}</small></span><button className="tutor-compact-button" type="button" onClick={addSelectionReference}>加入 Tutor</button><button className="tutor-text-button" type="button" onClick={() => setSelectionCandidate(null)}>取消</button></> : <span><strong>选择文本或代码可引用给 Tutor</strong><small>{selectionMessage ?? "引用会绑定当前 frozen document、block 与精确范围，不会拼进你的消息正文。"}</small></span>}
          </div>
        ) : null}
        {document.blocks.map((block) => <div key={block.block_id} data-lesson-block-id={block.block_id}><LessonBlockRenderer block={block} onCitation={focusCitation} renderExerciseGate={renderExerciseGate} /></div>)}
      </article>
      <LessonSourcesPanel sources={sources} selectedCitationId={selectedCitationId} onSelect={setSelectedCitationId} />
    </div>
  );
}

function selectionWithinElement(selection: Selection, element: HTMLElement | null): boolean {
  if (!element || selection.rangeCount === 0) return false;
  const range = selection.getRangeAt(0);
  return element.contains(range.commonAncestorContainer);
}

function lessonBlockPublicText(block: LessonBlock): string {
  switch (block.type) {
    case "heading": return [block.title, block.subtitle].join("\n");
    case "learning_objectives": return block.items.join("\n");
    case "concept": return [block.title, ...block.paragraphs].join("\n");
    case "authority_note": return [block.title, block.statement].join("\n");
    case "code_example": return [block.title, block.code, ...block.explanation].join("\n");
    case "comparison": return [block.title, ...block.columns, ...block.rows.flat(), block.conclusion].join("\n");
    case "hint": return [block.title, ...block.steps].join("\n");
    case "exercise_gate": return block.learner_prompt;
    case "summary": return block.points.join("\n");
    case "next_steps": return block.items.join("\n");
    default: { const unreachable: never = block; return String(unreachable); }
  }
}

function normalizeSelection(value: string): string {
  return value.normalize("NFKC").replace(/\r\n?/g, "\n").split(/\s+/u).filter(Boolean).join(" ");
}

function cssEscape(value: string): string {
  return globalThis.CSS?.escape ? globalThis.CSS.escape(value) : value.replace(/["\\\\]/g, "\\$&");
}

function documentRef(citationId: string): HTMLElement | null {
  return globalThis.document?.getElementById(`source-${citationId}`) ?? null;
}
