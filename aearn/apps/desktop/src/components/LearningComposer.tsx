import { type FormEvent, useRef, useEffect } from "react";

type LearningComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  streaming: boolean;
  sessionActive: boolean;
  canOpenNoteDrawer?: boolean;
  noteDrawerOpen?: boolean;
  onToggleNoteDrawer?: () => void;
  quickReplies?: string[];
  placeholder?: string;
  ariaLabel?: string;
  guidanceText?: string;
  hideNoteButton?: boolean;
};

/**
 * Assistant-ui-compatible composer for learning, onboarding, and review pages.
 *
 * Owns its own form submission, disables during streaming,
 * and shows guidance when no session is active.
 * Supports optional quick-reply chip buttons that fill+submit the composer.
 */
export function LearningComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  streaming,
  sessionActive,
  canOpenNoteDrawer = false,
  noteDrawerOpen = false,
  onToggleNoteDrawer,
  quickReplies,
  placeholder: placeholderOverride,
  ariaLabel: ariaLabelOverride,
  guidanceText,
  hideNoteButton = false,
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

  function handleQuickReply(text: string) {
    if (disabled || streaming || !sessionActive) return;
    onChange(text);
    // Use setTimeout to allow state to settle before submitting
    setTimeout(() => onSubmit(), 0);
  }

  const placeholder = placeholderOverride ?? (streaming
    ? "Agent 正在生成回答……"
    : !sessionActive
      ? "先从左侧路线进入一个知识点，再向 Agent 追问。"
      : "粘贴你的代码、运行输出、测试失败或请 Agent 解释错因……");

  const sendDisabled = disabled || streaming || value.trim().length === 0 || !sessionActive;

  return (
    <form className="composer-wrap" onSubmit={handleSubmit}>
      {quickReplies && quickReplies.length > 0 && !streaming && sessionActive && (
        <div className="quick-reply-chips" role="group" aria-label="快捷回复">
          {quickReplies.map((chip) => (
            <button
              className="quick-reply-chip"
              key={chip}
              type="button"
              disabled={disabled || streaming}
              onClick={() => handleQuickReply(chip)}
            >
              {chip}
            </button>
          ))}
        </div>
      )}
      <div className="composer">
        <textarea
          ref={textareaRef}
          aria-label={ariaLabelOverride ?? "代码练习输入框"}
          value={value}
          placeholder={placeholder}
          disabled={streaming || !sessionActive}
          onChange={(e) => onChange(e.target.value)}
        />
        {!hideNoteButton && onToggleNoteDrawer && (
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
        )}
        <button className="btn primary send-btn" type="submit" aria-label="发送" disabled={sendDisabled}>↑</button>
      </div>
      {guidanceText && !sessionActive && <div className="composer-guidance">{guidanceText}</div>}
      {!guidanceText && !sessionActive && <div className="composer-guidance">先进入一个 active learning session，composer 才会调用模型流式回答。</div>}
    </form>
  );
}
