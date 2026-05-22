import { lazy, Suspense } from "react";
import type { Language } from "../../types";

const MonacoEditor = lazy(() => import("@monaco-editor/react").then((mod) => ({ default: mod.default })));

type CodeEditorProps = {
  language: Language;
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  height?: string;
};

const LANGUAGE_MAP: Record<Language, string> = {
  javascript: "javascript",
  python: "python",
  html_css: "html",
  java: "java",
  cpp: "cpp",
};

export function CodeEditor({ language, value, onChange, readOnly = false, height = "300px" }: CodeEditorProps) {
  return (
    <Suspense fallback={<div className="tool-card">加载编辑器...</div>}>
      <MonacoEditor
        height={height}
        language={LANGUAGE_MAP[language] ?? "plaintext"}
        value={value}
        onChange={(val) => onChange(val ?? "")}
        theme="vs-light"
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
