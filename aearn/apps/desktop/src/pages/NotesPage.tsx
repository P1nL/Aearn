import type { NoteContext } from "../appTypes";
import type { NoteRecord } from "../types";

type NoteDraftState = {
  title: string;
  content: string;
  status: "加载中" | "未保存" | "保存中" | "已保存" | "保存失败";
  errorMessage: string | null;
};

type NotesPageProps = {
  loadState: "idle" | "loading" | "ready" | "error";
  errorMessage: string | null;
  notes: NoteRecord[];
  selectedKnowledgePointId: string | null;
  currentContext: NoteContext | null;
  selectedDraft: NoteDraftState | null;
  assistLoading: boolean;
  onSelectKnowledgePoint: (knowledgePointId: string) => void;
  onDraftTitleChange: (value: string) => void;
  onDraftContentChange: (value: string) => void;
  onRetrySave: () => void;
  onRequestAgentDraft: () => void;
  onCreateCurrentNote: () => void;
};

export function NotesPage({
  loadState,
  errorMessage,
  notes,
  selectedKnowledgePointId,
  currentContext,
  selectedDraft,
  assistLoading,
  onSelectKnowledgePoint,
  onDraftTitleChange,
  onDraftContentChange,
  onRetrySave,
  onRequestAgentDraft,
  onCreateCurrentNote,
}: NotesPageProps) {
  const grouped = groupNotesByLanguage(notes);
  const selectedNote = notes.find((item) => item.knowledge_point_id === selectedKnowledgePointId) ?? null;
  const canCreateCurrentContextNote =
    currentContext !== null &&
    !notes.some((item) => item.knowledge_point_id === currentContext.knowledgePointId);

  return (
    <div className="notes-layout">
      <aside className="notes-tree" aria-label="语言与知识点笔记导航">
        <div className="notes-tree-head">
          <div>
            <span className="eyebrow">Knowledge Notes</span>
            <h2>共享笔记</h2>
          </div>
          {canCreateCurrentContextNote && (
            <button className="btn primary ghost-btn" type="button" onClick={onCreateCurrentNote}>
              为「{currentContext?.knowledgePointTitle}」建笔记
            </button>
          )}
        </div>

        {loadState === "loading" && <div className="tool-card">正在读取笔记列表…</div>}
        {loadState === "error" && <div className="tool-card">错误：{errorMessage ?? "无法读取笔记列表"}</div>}
        {loadState === "ready" && notes.length === 0 && (
          <div className="tool-card">
            你还没有保存过任何知识点笔记。
            {currentContext ? ` 当前会话可直接创建「${currentContext.knowledgePointTitle}」的共享笔记。` : ""}
          </div>
        )}

        {grouped.map((group) => (
          <section className="notes-language-group" key={group.language}>
            <header>
              <span>{languageLabel(group.language)}</span>
              <strong>{group.items.length}</strong>
            </header>
            <div className="notes-language-items">
              {group.items.map((note) => (
                <button
                  key={note.id}
                  className={note.knowledge_point_id === selectedKnowledgePointId ? "note-tree-item active" : "note-tree-item"}
                  type="button"
                  onClick={() => onSelectKnowledgePoint(note.knowledge_point_id)}
                >
                  <span>{note.knowledge_point.title}</span>
                  <small>{note.module.title}</small>
                </button>
              ))}
            </div>
          </section>
        ))}
      </aside>

      <section className="note-editor-panel" aria-label="Markdown 笔记书写区域">
        {!selectedNote || !selectedDraft ? (
          <div className="notes-empty-panel">
            <h3>选择一条笔记</h3>
            <p>左侧按语言和知识点分组。抽屉与这里编辑的是同一条 note 记录。</p>
            {canCreateCurrentContextNote && (
              <button className="btn primary" type="button" onClick={onCreateCurrentNote}>
                直接创建当前知识点笔记
              </button>
            )}
          </div>
        ) : (
          <div className="notes-editor-shell">
            <header className="notes-editor-head">
              <div>
                <span className="eyebrow">{languageLabel(selectedNote.language)}</span>
                <h2>{selectedNote.knowledge_point.title}</h2>
                <p>
                  {selectedNote.module.title} · {selectedNote.course.title}
                </p>
              </div>
              <div className="notes-editor-actions">
                <span className={`note-save-chip ${selectedDraft.status === "保存失败" ? "error" : ""}`}>{selectedDraft.status}</span>
                <button className="btn primary ghost-btn" type="button" onClick={onRetrySave}>
                  立即保存
                </button>
                <button className="btn primary" type="button" disabled={assistLoading} onClick={onRequestAgentDraft}>
                  {assistLoading ? "补全中..." : "Agent 辅助补全"}
                </button>
              </div>
            </header>

            <div className="notes-editor-grid">
              <div className="notes-editor-stack">
                <label className="exercise-editor">
                  <span>标题</span>
                  <input className="notes-title-input" value={selectedDraft.title} onChange={(event) => onDraftTitleChange(event.target.value)} />
                </label>
                <textarea
                  className="note-content-editor"
                  aria-label="Markdown 笔记书写区域"
                  value={selectedDraft.content}
                  onChange={(event) => onDraftContentChange(event.target.value)}
                />
              </div>

              <aside className="notes-context-panel">
                <div className="tool-card">
                  <strong>知识点说明</strong>
                  <p>{selectedNote.knowledge_point.description ?? "当前知识点没有额外描述。重点记录你验证过的规律和反例。"}</p>
                </div>
                <div className="tool-card">
                  <strong>最近保存</strong>
                  <p>{formatDateTime(selectedNote.updated_at)}</p>
                  {selectedDraft.errorMessage && <p>保存错误：{selectedDraft.errorMessage}</p>}
                </div>
                <div className="tool-card">
                  <strong>Agent 草稿</strong>
                  <p>{selectedNote.agent_draft_content ?? "还没有辅助补全内容。可基于当前 note、最近尝试和知识点上下文生成结构化提示。"}</p>
                </div>
              </aside>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function groupNotesByLanguage(notes: NoteRecord[]): Array<{ language: NoteRecord["language"]; items: NoteRecord[] }> {
  const groups = new Map<NoteRecord["language"], NoteRecord[]>();
  for (const note of notes) {
    const list = groups.get(note.language) ?? [];
    list.push(note);
    groups.set(note.language, list);
  }
  return Array.from(groups.entries()).map(([language, items]) => ({
    language,
    items,
  }));
}

function languageLabel(language: NoteRecord["language"]): string {
  if (language === "javascript") {
    return "JavaScript";
  }
  if (language === "python") {
    return "Python";
  }
  if (language === "html_css") {
    return "HTML / CSS";
  }
  if (language === "cpp") {
    return "C++";
  }
  return "Java";
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
