import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const artifactDir = resolve(process.cwd(), "src/features/tutor/artifacts");
const safeMarkdownSource = readFileSync(resolve(artifactDir, "SafeMarkdown.tsx"), "utf8");
const registrySource = readFileSync(resolve(artifactDir, "ArtifactRendererRegistry.tsx"), "utf8");
const cssSource = readFileSync(resolve(process.cwd(), "src/styles/30-tutor-harness.css"), "utf8");

describe("Artifact shell source guards", () => {
  it("never introduces raw HTML execution seams", () => {
    expect(safeMarkdownSource).not.toContain("dangerouslySetInnerHTML");
    expect(safeMarkdownSource).not.toContain("innerHTML");
    expect(safeMarkdownSource).not.toContain("DOMParser");
    expect(registrySource).not.toContain("React.lazy");
    expect(registrySource).not.toContain("import(");
    expect(artifactDir).toContain("artifacts");
  });

  it("keeps the artifact section responsive, touchable, motion-aware, and non-draggable", () => {
    const section = cssSource.slice(cssSource.indexOf("Child 03 conversation-native Artifact"));
    expect(section).toContain("container-type: inline-size");
    expect(section).toContain("@container tutor-timeline (max-width: 720px)");
    expect(section).toContain("min-height: 44px");
    expect(section).toContain("prefers-reduced-motion: reduce");
    expect(section).toContain("max-width: 100%");
    expect(section).not.toMatch(/resize\s*:/);
    expect(section).not.toMatch(/splitter|drag-handle|draggable/i);
  });
});
