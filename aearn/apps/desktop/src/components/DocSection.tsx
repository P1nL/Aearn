import { useState } from "react";

import type { DocumentationSection } from "../types";

type DocSectionProps = {
  section: DocumentationSection;
  defaultExpanded: boolean;
  onReference: (text: string) => void;
};

export function DocSection({ section, defaultExpanded, onReference }: DocSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <section className="doc-section" id={`doc-${section.id}`}>
      <button
        className="doc-section-title"
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
      >
        <span>{section.title}</span>
        <span aria-hidden="true">{expanded ? "-" : "+"}</span>
      </button>
      {expanded && (
        <div className="doc-section-body">
          <MarkdownLikeText text={section.content_markdown} />
          {section.code_blocks.map((block, index) => (
            <figure className="doc-code-block" key={`${section.id}-${index}`}>
              <figcaption>
                <span>
                  <strong>{codeBlockSourceLabel(block.source_type)}</strong>
                  {displayCodeBlockCaption(block.caption)}
                </span>
                <button
                  className="doc-reference-btn"
                  type="button"
                  onClick={() => onReference(block.code)}
                >
                  引用到对话
                </button>
              </figcaption>
              <pre>
                <code>{block.code}</code>
              </pre>
            </figure>
          ))}
        </div>
      )}
    </section>
  );
}

function codeBlockSourceLabel(sourceType: string | null | undefined): string {
  if (sourceType === "official") return "官方示例";
  if (sourceType === "aearn") return "Aearn 示例";
  if (sourceType === "trusted") return "可信示例";
  return "示例";
}

function displayCodeBlockCaption(caption: string): string {
  return caption.replace(/^(Aearn 示例|官方示例|可信示例)：/, "").trim();
}

function MarkdownLikeText({ text }: { text: string }) {
  const lines = text.split("\n").map((line) => line.trimEnd());
  return (
    <div className="doc-markdown">
      {lines.map((line, index) => {
        if (!line.trim()) {
          return <div className="doc-break" key={index} aria-hidden="true" />;
        }
        if (line.startsWith("- ")) {
          return <p className="doc-list-line" key={index}>{line}</p>;
        }
        return <p key={index}>{line}</p>;
      })}
    </div>
  );
}
