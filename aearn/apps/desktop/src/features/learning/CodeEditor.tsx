import { lazy, Suspense } from "react";
import type { Monaco } from "@monaco-editor/react";
import type { Language } from "../../types";

const MonacoEditor = lazy(() => import("@monaco-editor/react").then((mod) => ({ default: mod.default })));

type CodeEditorProps = {
  language: Language;
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  height?: string;
  dark?: boolean;
};

const LANGUAGE_MAP: Record<Language, string> = {
  javascript: "javascript",
  python: "python",
  typescript: "typescript",
  sql: "sql",
  html_css: "html",
  java: "java",
  go: "go",
  csharp: "csharp",
};

function handleBeforeMount(monaco: Monaco) {
  monaco.editor.defineTheme("aearn-dark", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "keyword", foreground: "5cc9a0", fontStyle: "bold" },
      { token: "string", foreground: "b8d4a8" },
      { token: "comment", foreground: "5e6b62", fontStyle: "italic" },
      { token: "number", foreground: "8fd4b4" },
      { token: "type", foreground: "7ecbab" },
      { token: "variable", foreground: "e4ece4" },
      { token: "function", foreground: "5cc9a0" },
    ],
    colors: {
      "editor.background": "#1a2b23",
      "editor.foreground": "#e4ece4",
      "editor.lineHighlightBackground": "#2f7d6326",
      "editorLineNumber.foreground": "#5e6b62",
      "editorLineNumber.activeForeground": "#5cc9a0",
      "editor.selectionBackground": "#2f7d6340",
      "editorCursor.foreground": "#5cc9a0",
      "editor.inactiveSelectionBackground": "#2f7d6320",
      "editorIndentGuide.background": "#2f7d6330",
      "scrollbarSlider.background": "#2f7d6330",
      "scrollbarSlider.hoverBackground": "#2f7d6350",
    },
  });
}

export function CodeEditor({ language, value, onChange, readOnly = false, height = "300px", dark = false }: CodeEditorProps) {
  return (
    <Suspense fallback={<div className="tool-card">加载编辑器...</div>}>
      <MonacoEditor
        height={height}
        language={LANGUAGE_MAP[language] ?? "plaintext"}
        value={value}
        onChange={(val) => onChange(val ?? "")}
        theme={dark ? "aearn-dark" : "vs-light"}
        beforeMount={dark ? handleBeforeMount : undefined}
        options={{
          readOnly,
          minimap: { enabled: false },
          fontSize: 14,
          lineNumbers: "on",
          scrollBeyondLastLine: false,
          automaticLayout: true,
          tabSize: 2,
          wordWrap: "on",
          renderLineHighlight: "line",
          folding: false,
          overviewRulerBorder: false,
          hideCursorInOverviewRuler: true,
          scrollbar: {
            verticalScrollbarSize: 8,
            horizontalScrollbarSize: 8,
          },
        }}
      />
    </Suspense>
  );
}
