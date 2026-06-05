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
                <span>{block.caption}</span>
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
