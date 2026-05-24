import { type FormEvent, useRef, useEffect } from "react";

type LearningComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  streaming: boolean;
  sessionActive: boolean;
  canOpenNoteDrawer: boolean;
  noteDrawerOpen: boolean;
  onToggleNoteDrawer: () => void;
};

/**
 * Assistant-ui-compatible composer for the learning page.
 *
 * Owns its own form submission, disables during streaming,
 * and shows guidance when no session is active.
 */
export function LearningComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  streaming,
  sessionActive,
  canOpenNoteDrawer,
  noteDrawerOpen,
  onToggleNoteDrawer,
}: LearningComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!streaming && sessionActive && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [streaming, sessionActive]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled || streaming || !sessionActive) return;
    if (value.trim().length === 0) return;
    onSubmit();
  }

  const placeholder = streaming
    ? "Agent 正在生成回答……"
    : !sessionActive
      ? "先从左侧路线进入一个知识点，再向 Agent 追问。"
      : "粘贴你的代码、运行输出、测试失败或请 Agent 解释错因……";

  const sendDisabled = disabled || streaming || value.trim().length === 0 || !sessionActive;

  return (
    <form className="composer-wrap" onSubmit={handleSubmit}>
      <div className="composer">
        <textarea
          ref={textareaRef}
          aria-label="代码练习输入框"
          value={value}
          placeholder={placeholder}
          disabled={streaming || !sessionActive}
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          className="btn primary send-btn note-inline-btn"
          type="button"
          aria-label={noteDrawerOpen ? "关闭知识点笔记" : "打开知识点笔记"}
          aria-controls="noteDrawer"
          aria-expanded={noteDrawerOpen}
          disabled={!noteDrawerOpen && !canOpenNoteDrawer}
          onClick={onToggleNoteDrawer}
        >
          <img src="/note.png" alt="" />
        </button>
        <button className="btn primary send-btn" type="submit" aria-label="发送" disabled={sendDisabled}>↑</button>
      </div>
      {!sessionActive && <div className="composer-guidance">先进入一个 active learning session，composer 才会调用模型流式回答。</div>}
    </form>
  );
}
