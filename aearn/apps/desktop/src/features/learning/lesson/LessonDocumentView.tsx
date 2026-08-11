import type { ReactNode } from "react";
import { useState } from "react";

import type { LessonAssignment, LessonCitation, LessonDocument, LessonExerciseGateBlock } from "../../../types";
import { LessonBlockRenderer } from "./LessonBlockRenderer";
import { LessonSourcesPanel } from "./LessonSourcesPanel";

type LessonDocumentViewProps = {
  document: LessonDocument;
  assignment: LessonAssignment;
  sources: LessonCitation[];
  renderExerciseGate?: (block: LessonExerciseGateBlock) => ReactNode;
};

export function LessonDocumentView({ document, assignment, sources, renderExerciseGate }: LessonDocumentViewProps) {
  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(sources[0]?.citation_id ?? null);

  function focusCitation(citationId: string) {
    setSelectedCitationId(citationId);
    const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    globalThis.requestAnimationFrame(() => documentRef(citationId)?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest" }));
  }

  return (
    <div className="lesson-reading-layout">
      <article className="lesson-document" aria-label={document.title}>
        <div className="lesson-document-meta"><span>版本 {assignment.assignment_version}</span><span>{assignment.started_at ? "已开始 · 内容已冻结" : "尚未开始 · 可冻结当前版本"}</span><span>{document.content_standard_version}</span></div>
        {document.blocks.map((block) => <LessonBlockRenderer key={block.block_id} block={block} onCitation={focusCitation} renderExerciseGate={renderExerciseGate} />)}
      </article>
      <LessonSourcesPanel sources={sources} selectedCitationId={selectedCitationId} onSelect={setSelectedCitationId} />
    </div>
  );
}

function documentRef(citationId: string): HTMLElement | null {
  return globalThis.document?.getElementById(`source-${citationId}`) ?? null;
}
