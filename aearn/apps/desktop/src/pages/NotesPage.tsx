type NotesPageProps = {
  noteContent: string;
  onNoteContentChange: (value: string) => void;
};

export function NotesPage({ noteContent, onNoteContentChange }: NotesPageProps) {
  return (
    <div className="notes-layout">
      <section className="note-editor-panel" aria-label="Markdown 笔记书写区域">
        <textarea
          className="note-content-editor"
          aria-label="Markdown 笔记书写区域"
          value={noteContent}
          onChange={(event) => onNoteContentChange(event.target.value)}
        />
      </section>
    </div>
  );
}
