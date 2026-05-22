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
      {/* 左侧：紧凑树形列表 */}
      <aside className="notes-sidebar" aria-label="笔记导航">
        <div className="notes-sidebar-head">
          <h3>笔记</h3>
          {canCreateCurrentContextNote && (
            <button className="btn small" type="button" onClick={onCreateCurrentNote} title={`为「${currentContext?.knowledgePointTitle}」建笔记`}>
              +
            </button>
          )}
        </div>

        {loadState === "loading" && <p className="notes-hint">加载中…</p>}
        {loadState === "error" && <p className="notes-hint notes-hint-error">{errorMessage ?? "无法读取笔记"}</p>}
        {loadState === "ready" && notes.length === 0 && (
          <div className="notes-empty-tree">
            <p>还没有笔记</p>
            {canCreateCurrentContextNote && (
              <button className="btn small primary" type="button" onClick={onCreateCurrentNote}>
                创建第一条
              </button>
            )}
          </div>
        )}

        {grouped.map((group) => (
          <section className="notes-group" key={group.language}>
            <div className="notes-group-label">{languageLabel(group.language)}</div>
            {group.items.map((note) => (
              <button
                key={note.id}
                className={note.knowledge_point_id === selectedKnowledgePointId ? "notes-item active" : "notes-item"}
                type="button"
                onClick={() => onSelectKnowledgePoint(note.knowledge_point_id)}
              >
                <span className="notes-item-title">{note.knowledge_point.title}</span>
                <span className="notes-item-meta">{note.module.title}</span>
              </button>
            ))}
          </section>
        ))}
      </aside>

      {/* 右侧：编辑器 */}
      <section className="notes-editor" aria-label="笔记编辑">
        {!selectedNote || !selectedDraft ? (
          <div className="notes-empty-editor">
            <div className="notes-empty-icon">&#9998;</div>
            <h3>选择一条笔记开始编辑</h3>
            <p>从左侧列表选择知识点，或创建新笔记</p>
            {canCreateCurrentContextNote && (
              <button className="btn primary" type="button" onClick={onCreateCurrentNote}>
                为「{currentContext?.knowledgePointTitle}」创建笔记
              </button>
            )}
          </div>
        ) : (
          <>
            {/* 编辑器头部 */}
            <header className="notes-editor-header">
              <div className="notes-editor-title-row">
                <div>
                  <span className="notes-editor-lang">{languageLabel(selectedNote.language)}</span>
                  <h2 className="notes-editor-title">{selectedNote.knowledge_point.title}</h2>
                </div>
                <div className="notes-editor-toolbar">
                  <span className={`notes-save-dot ${saveStatusClass(selectedDraft.status)}`} title={selectedDraft.status} />
                  {selectedDraft.status === "保存失败" && (
                    <button className="btn small" type="button" onClick={onRetrySave}>重试</button>
                  )}
                  <button className="btn small primary" type="button" disabled={assistLoading} onClick={onRequestAgentDraft}>
                    {assistLoading ? "生成中…" : "AI 补全"}
                  </button>
                </div>
              </div>
              <p className="notes-editor-breadcrumb">{selectedNote.module.title} · {selectedNote.course.title}</p>
            </header>

            {/* Agent 草稿提示（可折叠） */}
            {selectedNote.agent_draft_content && (
              <details className="notes-agent-draft">
                <summary>AI 建议</summary>
                <div className="notes-agent-draft-content">{selectedNote.agent_draft_content}</div>
              </details>
            )}

            {/* 编辑器主体 */}
            <textarea
              className="notes-textarea"
              aria-label="Markdown 笔记内容"
              placeholder="在这里记录你的学习笔记…&#10;&#10;支持 Markdown 格式"
              value={selectedDraft.content}
              onChange={(event) => onDraftContentChange(event.target.value)}
            />
          </>
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

function saveStatusClass(status: NoteDraftState["status"]): string {
  if (status === "已保存") {
    return "saved";
  }
  if (status === "保存失败") {
    return "error";
  }
  if (status === "保存中" || status === "加载中") {
    return "saving";
  }
  return "unsaved";
}
