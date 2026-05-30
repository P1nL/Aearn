import { useState } from "react";
import type { ToolUIProps, ExerciseCardArgs } from "./types";

export function ExerciseCard({ args, status, onAction }: ToolUIProps<ExerciseCardArgs>) {
  const [filledBlanks, setFilledBlanks] = useState<Record<string, string>>(
    Object.fromEntries(args.blanks.map((b) => [b.blank_key, ""]))
  );
  const [code, setCode] = useState(args.starter_code);

  const difficultyLabel = args.difficulty <= 2 ? "入门" : args.difficulty <= 4 ? "基础" : args.difficulty <= 6 ? "中等" : "进阶";

  return (
    <article className="gen-card gen-exercise-card" aria-label="练习卡片">
      <header className="gen-card-header">
        <span className="gen-card-kicker">{exerciseTypeLabel(args.exercise_type)}</span>
        <span className="gen-card-badge">{difficultyLabel} · 约 {args.estimated_minutes} 分钟</span>
      </header>

      <h3 className="gen-card-title">{args.title}</h3>
      <p className="gen-exercise-prompt">{args.prompt_markdown}</p>

      {args.blanks.length > 0 && (
        <div className="gen-exercise-blanks">
          {args.blanks.map((blank) => (
            <label className="gen-exercise-blank" key={blank.blank_key}>
              <span className="gen-exercise-blank-label">{blank.blank_key}</span>
              <input
                className="gen-exercise-blank-input"
                value={filledBlanks[blank.blank_key] ?? ""}
                placeholder={blank.placeholder}
                onChange={(e) => setFilledBlanks((prev) => ({ ...prev, [blank.blank_key]: e.target.value }))}
                disabled={status === "pending"}
              />
              <span className="gen-exercise-blank-hint">{blank.expected_concept}</span>
            </label>
          ))}
        </div>
      )}

      <div className="gen-exercise-editor">
        <div className="gen-exercise-editor-header">
          <span>{args.language}</span>
          <span className="gen-exercise-runtime">{runtimeLabel(args.runtime_tier)}</span>
        </div>
        <textarea
          className="gen-exercise-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          disabled={status === "pending"}
          rows={Math.min(code.split("\n").length + 1, 16)}
          spellCheck={false}
        />
      </div>

      {status !== "pending" && (
        <div className="gen-card-actions">
          <button
            className="btn ghost"
            type="button"
            onClick={() => onAction?.("run_preview", { code, filledBlanks })}
          >
            预览
          </button>
          <button
            className="btn primary"
            type="button"
            onClick={() => onAction?.("run_tests", { code, filledBlanks })}
          >
            运行测试
          </button>
          <button
            className="btn ghost"
            type="button"
            onClick={() => onAction?.("request_hint", { blank_key: Object.keys(filledBlanks)[0] })}
          >
            提示
          </button>
        </div>
      )}
    </article>
  );
}

function exerciseTypeLabel(type: ExerciseCardArgs["exercise_type"]): string {
  switch (type) {
    case "code_blank": return "代码填空";
    case "fix_bug": return "修复 Bug";
    case "implement_function": return "实现函数";
    case "explain_code": return "解释代码";
    case "review_ai_patch": return "AI 改动审查";
  }
}

function runtimeLabel(tier: string): string {
  switch (tier) {
    case "browser_preview": return "浏览器预览";
    case "python_stdout_test": return "Python 测试";
    default: return "静态补全";
  }
}
