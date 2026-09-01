import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const artifactDir = resolve(process.cwd(), "src/features/tutor/artifacts");
const safeMarkdownSource = readFileSync(resolve(artifactDir, "SafeMarkdown.tsx"), "utf8");
const registrySource = readFileSync(resolve(artifactDir, "ArtifactRendererRegistry.tsx"), "utf8");
const executionResultSource = readFileSync(resolve(artifactDir, "ExecutionResultArtifact.tsx"), "utf8");
const codeEditorSource = readFileSync(resolve(artifactDir, "CodeEditorArtifact.tsx"), "utf8");
const browserPreviewSource = readFileSync(resolve(artifactDir, "BrowserPreviewArtifact.tsx"), "utf8");
const previewHostSource = readFileSync(resolve(process.cwd(), "src-tauri/src/preview_host.rs"), "utf8");
const tauriBuildSource = readFileSync(resolve(process.cwd(), "src-tauri/build.rs"), "utf8");
const capability = JSON.parse(readFileSync(resolve(process.cwd(), "src-tauri/capabilities/default.json"), "utf8")) as Record<string, unknown>;
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

  it("keeps execution result rendering typed, local, and free of a second authority", () => {
    expect(executionResultSource).not.toContain("dangerouslySetInnerHTML");
    expect(executionResultSource).not.toContain("safe_feedback");
    expect(executionResultSource).not.toMatch(/\.score\b/);
    expect(executionResultSource).not.toMatch(/Submit|提交/);
    expect(executionResultSource).toContain("sourceArtifactReference");
    expect(executionResultSource).toContain("其他 {result.passed_test_count} 项通过");
    expect(executionResultSource).toContain('result.presentation.kind === "table_result_v1"');
  });

  it("keeps the artifact section responsive, touchable, motion-aware, and non-draggable", () => {
    const section = cssSource.slice(cssSource.indexOf("Child 03 conversation-native Artifact"));
    expect(section).toContain("container-type: inline-size");
    expect(section).toContain("@container tutor-timeline (max-width: 720px)");
    expect(section).toContain("min-height: 44px");
    expect(section).toContain("prefers-reduced-motion: reduce");
    expect(section).toContain("max-width: 100%");
    expect(section).toContain(".execution-result-table-scroll");
    expect(section).toContain("overflow-x: auto");
    expect(section).toContain("summary:focus-visible");
    expect(section).not.toMatch(/resize\s*:/);
    expect(section).not.toMatch(/splitter|drag-handle|draggable/i);
  });

  it("keeps learner source out of the main DOM and isolates Preview capability", () => {
    const frontend = `${codeEditorSource}\n${browserPreviewSource}`;
    expect(frontend).not.toMatch(/dangerouslySetInnerHTML|srcDoc|<iframe|new Function|\beval\s*\(/);
    expect(frontend).toContain("PREVIEW_HOST_UNAVAILABLE");
    expect(previewHostSource).toContain("WebviewUrl::CustomProtocol(url)");
    expect(previewHostSource).toContain('sandbox=\"allow-scripts\"');
    expect(previewHostSource).toContain("NewWindowResponse::Deny");
    expect(previewHostSource).toContain("DownloadEvent::Requested");
    expect(tauriBuildSource).toContain("AppManifest::new().commands(APP_COMMANDS)");
    expect(capability).toMatchObject({
      webviews: ["main"],
      permissions: [
        "core:default",
        "allow-preview-host-create",
        "allow-preview-host-update-source",
        "allow-preview-host-set-bounds",
        "allow-preview-host-recreate",
        "allow-preview-host-close",
      ],
    });
    expect(capability).not.toHaveProperty("windows");
  });

  it("keeps the Editor/Preview split fixed at 50:50 and stacks it without a draggable seam", () => {
    expect(cssSource).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
    expect(cssSource).toContain("grid-template-rows: repeat(2, minmax(240px, 1fr))");
    expect(cssSource).not.toMatch(/splitter|drag-handle|draggable/i);
  });
});
