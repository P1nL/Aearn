import type { NoteRecord } from "../types";
import type { NoteDraftState } from "../stores/useNotesStore";
import { useNotesStore } from "../stores/useNotesStore";

type NoteDrawerProps = {
  drawerKnowledgePointId: string | null;
  drawerNote: NoteRecord | null;
  drawerDraft: NoteDraftState | null;
  userId: string | undefined;
  lastAttemptId: string | undefined;
};

export function NoteDrawer({ drawerKnowledgePointId, drawerNote, drawerDraft, userId, lastAttemptId }: NoteDrawerProps) {
  const notes = useNotesStore();

  return (
    <section id="noteDrawer" className="drawer open" aria-label="知识点笔记抽屉">
      <div className="drawer-head">
        <div>
          <h2>{notes.drawerContext?.knowledgePointTitle ?? "知识点笔记"}</h2>
          {drawerNote && (
            <p className="drawer-note-meta">
              {drawerNote.module.title} · {drawerNote.course.title}
            </p>
          )}
        </div>
        <div className="note-status">
          <span>{drawerDraft?.status ?? "加载中"}</span>
          <button
            className="icon-btn"
            type="button"
            aria-label="保存笔记"
            onClick={() => drawerKnowledgePointId && void notes.saveByKnowledgePointId(drawerKnowledgePointId)}
          >
            ✓
          </button>
          <button
            className="btn primary ghost-btn"
            type="button"
            disabled={!drawerKnowledgePointId || Boolean(drawerKnowledgePointId && notes.assistBusy[drawerKnowledgePointId])}
            onClick={() =>
              drawerKnowledgePointId &&
              userId &&
              void notes.requestAgentDraft(drawerKnowledgePointId, userId, notes.drawerContext, lastAttemptId)
            }
          >
            {drawerKnowledgePointId && notes.assistBusy[drawerKnowledgePointId] ? "补全中..." : "Agent 补全"}
          </button>
        </div>
      </div>
      {!drawerDraft ? (
        <div className="tool-card">正在加载当前知识点的笔记…</div>
      ) : (
        <div className="drawer-note-layout">
          <textarea
            className="drawer-editor"
            aria-label="知识点笔记编辑器"
            value={drawerDraft.content}
            onChange={(event) => {
              if (drawerKnowledgePointId) {
                notes.updateDraftContent(drawerKnowledgePointId, event.target.value);
              }
            }}
          />
          <aside className="drawer-note-side">
            <div className="tool-card">
              <strong>标题</strong>
              <input
                className="notes-title-input"
                value={drawerDraft.title}
                onChange={(event) => {
                  if (drawerKnowledgePointId) {
                    notes.updateDraftTitle(drawerKnowledgePointId, event.target.value);
                  }
                }}
              />
            </div>
            <div className="tool-card">
              <strong>辅助补全</strong>
              <p>{drawerNote?.agent_draft_content ?? "还没有辅助补全内容。点击上方按钮生成结构化建议。"}</p>
            </div>
            {drawerDraft.errorMessage && (
              <div className="tool-card">
                <strong>保存错误</strong>
                <p>{drawerDraft.errorMessage}</p>
              </div>
            )}
          </aside>
        </div>
      )}
    </section>
  );
}
