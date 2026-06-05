import { useRef, useState } from "react";

import type { KnowledgePointDocumentationResponse } from "../types";
import { DocSection } from "./DocSection";

export type DocumentationPanelState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: KnowledgePointDocumentationResponse }
  | { status: "error"; message: string };

type DocumentationPanelProps = {
  state: DocumentationPanelState;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onRetry: () => void;
  onReference: (text: string) => void;
};

const DEFAULT_EXPANDED_SECTIONS = new Set(["core_concept", "syntax", "examples"]);

export function DocumentationPanel({
  state,
  collapsed,
  onCollapsedChange,
  onRetry,
  onReference,
}: DocumentationPanelProps) {
  const [selectedText, setSelectedText] = useState("");
  const panelRef = useRef<HTMLElement | null>(null);

  function captureSelection() {
    const selection = window.getSelection();
    const text = selection?.toString().trim() ?? "";
    if (!text || !panelRef.current || !selection?.anchorNode) {
      setSelectedText("");
      return;
    }
    if (!panelRef.current.contains(selection.anchorNode)) {
      setSelectedText("");
      return;
    }
    setSelectedText(text.slice(0, 500));
  }

  if (collapsed) {
    return (
      <aside className="documentation-panel collapsed" aria-label="知识点文档">
        <button className="doc-collapse-tab" type="button" onClick={() => onCollapsedChange(false)}>
          展开文档
        </button>
      </aside>
    );
  }

  return (
    <aside className="documentation-panel" aria-label="知识点文档" ref={panelRef} onMouseUp={captureSelection}>
      <header className="doc-panel-header">
        <div>
          <span className="doc-kicker">Knowledge Doc</span>
          <h2>{state.status === "ready" ? state.data.title : "知识点文档"}</h2>
        </div>
        <button
          className="icon-btn doc-collapse-btn"
          type="button"
          aria-label="折叠文档面板"
          onClick={() => onCollapsedChange(true)}
        >
          <span aria-hidden="true">›</span>
        </button>
      </header>

      {state.status === "loading" && <div className="doc-panel-state">正在加载当前知识点文档…</div>}

      {state.status === "error" && (
        <div className="doc-panel-state error">
          <p>{state.message}</p>
          <button className="btn ghost-btn" type="button" onClick={onRetry}>
            重试加载
          </button>
        </div>
      )}

      {state.status === "idle" && <div className="doc-panel-state">进入知识点后会自动加载文档。</div>}

      {state.status === "ready" && (
        <>
          <p className="doc-summary">{state.data.summary}</p>
          <nav className="doc-toc" aria-label="文档目录">
            {state.data.sections.map((section) => (
              <a href={`#doc-${section.id}`} key={section.id}>
                {section.title}
              </a>
            ))}
          </nav>

          {selectedText && (
            <div className="doc-selection-popover">
              <span>已选中 {selectedText.length} 字</span>
              <button
                className="doc-reference-btn"
                type="button"
                onClick={() => {
                  onReference(selectedText);
                  setSelectedText("");
                  window.getSelection()?.removeAllRanges();
                }}
              >
                引用到对话
              </button>
            </div>
          )}

          <div className="doc-sections">
            {state.data.sections.map((section) => (
              <DocSection
                defaultExpanded={DEFAULT_EXPANDED_SECTIONS.has(section.id)}
                key={section.id}
                section={section}
                onReference={(text) => onReference(text.slice(0, 500))}
              />
            ))}
          </div>

          {state.data.references.length > 0 && (
            <footer className="doc-references">
              <h3>参考来源</h3>
              {state.data.references.map((reference) => (
                <p key={`${reference.title}-${reference.url}`}>
                  {reference.url ? (
                    <a href={reference.url} target="_blank" rel="noreferrer">
                      {reference.title}
                    </a>
                  ) : (
                    reference.title
                  )}
                </p>
              ))}
            </footer>
          )}
        </>
      )}
    </aside>
  );
}
