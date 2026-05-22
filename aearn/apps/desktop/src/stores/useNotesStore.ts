import { create } from "zustand";
import { toast } from "sonner";

import {
  createNote,
  fetchNotes,
  requestNoteAgentDraft,
  updateNote,
} from "../api";
import type { NoteRecord } from "../types";
import type { NoteContext } from "../appTypes";
import { getErrorInfo } from "../lib/errorMessages";

type NoteDraftState = {
  title: string;
  content: string;
  status: "加载中" | "未保存" | "保存中" | "已保存" | "保存失败";
  errorMessage: string | null;
};

type NotesStore = {
  loadState: "idle" | "loading" | "ready" | "error";
  errorMessage: string | null;
  notesList: NoteRecord[];
  notesByKnowledgePointId: Record<string, NoteRecord>;
  noteDrafts: Record<string, NoteDraftState>;
  assistBusy: Record<string, boolean>;
  drawerOpen: boolean;
  drawerContext: NoteContext | null;
  reviewNoteContext: NoteContext | null;
  pageSelection: string | null;

  setDrawerOpen: (open: boolean) => void;
  setDrawerContext: (context: NoteContext | null) => void;
  setReviewNoteContext: (context: NoteContext | null) => void;
  setPageSelection: (id: string | null) => void;
  updateDraftContent: (knowledgePointId: string, content: string) => void;
  updateDraftTitle: (knowledgePointId: string, title: string) => void;
  syncNoteRecord: (note: NoteRecord, draftStatus?: NoteDraftState["status"]) => void;
  setDraftStatus: (knowledgePointId: string, status: NoteDraftState["status"], errorMessage?: string | null) => void;
  loadIndex: (userId: string, signal?: AbortSignal) => Promise<void>;
  ensureForContext: (userId: string, context: NoteContext) => Promise<NoteRecord | null>;
  saveByKnowledgePointId: (knowledgePointId: string) => Promise<boolean>;
  requestAgentDraft: (knowledgePointId: string, userId: string, context?: NoteContext | null, attemptId?: string) => Promise<void>;
  reset: () => void;
};

function upsertNote(current: NoteRecord[], note: NoteRecord): NoteRecord[] {
  const idx = current.findIndex((item) => item.id === note.id);
  if (idx === -1) {
    return [note, ...current];
  }
  const next = [...current];
  next[idx] = note;
  return next;
}

function sortByUpdatedAt(notes: NoteRecord[]): NoteRecord[] {
  return [...notes].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
}

export const useNotesStore = create<NotesStore>((set, get) => ({
  loadState: "idle",
  errorMessage: null,
  notesList: [],
  notesByKnowledgePointId: {},
  noteDrafts: {},
  assistBusy: {},
  drawerOpen: false,
  drawerContext: null,
  reviewNoteContext: null,
  pageSelection: null,

  setDrawerOpen: (open) => set({ drawerOpen: open }),
  setDrawerContext: (context) => set({ drawerContext: context }),
  setReviewNoteContext: (context) => set({ reviewNoteContext: context }),
  setPageSelection: (id) => set({ pageSelection: id }),

  updateDraftContent: (knowledgePointId, content) => {
    set((state) => {
      const prev = state.noteDrafts[knowledgePointId];
      if (!prev) return state;
      return {
        noteDrafts: {
          ...state.noteDrafts,
          [knowledgePointId]: { ...prev, content, status: "未保存", errorMessage: null },
        },
      };
    });
  },

  updateDraftTitle: (knowledgePointId, title) => {
    set((state) => {
      const prev = state.noteDrafts[knowledgePointId];
      if (!prev) return state;
      return {
        noteDrafts: {
          ...state.noteDrafts,
          [knowledgePointId]: { ...prev, title, status: "未保存", errorMessage: null },
        },
      };
    });
  },

  syncNoteRecord: (note, draftStatus = "已保存") => {
    set((state) => ({
      notesByKnowledgePointId: {
        ...state.notesByKnowledgePointId,
        [note.knowledge_point_id]: note,
      },
      notesList: sortByUpdatedAt(upsertNote(state.notesList, note)),
      noteDrafts: {
        ...state.noteDrafts,
        [note.knowledge_point_id]: {
          title: note.title,
          content: note.content_markdown,
          status: draftStatus,
          errorMessage: null,
        },
      },
    }));
  },

  setDraftStatus: (knowledgePointId, status, errorMessage = null) => {
    set((state) => {
      const prev = state.noteDrafts[knowledgePointId];
      if (!prev) return state;
      return {
        noteDrafts: {
          ...state.noteDrafts,
          [knowledgePointId]: { ...prev, status, errorMessage },
        },
      };
    });
  },

  loadIndex: async (userId, signal) => {
    set({ loadState: "loading", errorMessage: null });
    try {
      const response = await fetchNotes({ userId, limit: 50, signal });
      const sorted = sortByUpdatedAt(response.items);
      set({
        notesList: sorted,
        notesByKnowledgePointId: Object.fromEntries(response.items.map((item) => [item.knowledge_point_id, item])),
        loadState: "ready",
        pageSelection: sorted[0]?.knowledge_point_id ?? null,
      });
    } catch (error) {
      if (signal?.aborted) return;
      const info = getErrorInfo(error);
      set({ loadState: "error", errorMessage: info.message });
    }
  },

  ensureForContext: async (userId, context) => {
    const { syncNoteRecord } = get();
    set((state) => ({
      noteDrafts: {
        ...state.noteDrafts,
        [context.knowledgePointId]: {
          title: state.noteDrafts[context.knowledgePointId]?.title ?? context.knowledgePointTitle,
          content: state.noteDrafts[context.knowledgePointId]?.content ?? "",
          status: "加载中",
          errorMessage: null,
        },
      },
    }));
    try {
      const response = await fetchNotes({ userId, knowledgePointId: context.knowledgePointId, limit: 1 });
      const existing = response.items[0];
      if (existing) {
        syncNoteRecord(existing);
        return existing;
      }
      const created = await createNote({
        userId,
        knowledgePointId: context.knowledgePointId,
        title: context.knowledgePointTitle,
        contentMarkdown: "",
        source: { sessionId: context.sessionId, attemptId: context.attemptId },
      });
      syncNoteRecord(created);
      set({ loadState: "ready" });
      return created;
    } catch (error) {
      const info = getErrorInfo(error);
      set((state) => ({
        noteDrafts: {
          ...state.noteDrafts,
          [context.knowledgePointId]: {
            title: state.noteDrafts[context.knowledgePointId]?.title ?? context.knowledgePointTitle,
            content: state.noteDrafts[context.knowledgePointId]?.content ?? "",
            status: "保存失败",
            errorMessage: info.message,
          },
        },
      }));
      return null;
    }
  },

  saveByKnowledgePointId: async (knowledgePointId) => {
    const { notesByKnowledgePointId, noteDrafts, syncNoteRecord, setDraftStatus } = get();
    const note = notesByKnowledgePointId[knowledgePointId];
    const draft = noteDrafts[knowledgePointId];
    if (!note || !draft) return false;
    setDraftStatus(knowledgePointId, "保存中");
    try {
      const updated = await updateNote({
        noteId: note.id,
        title: draft.title,
        contentMarkdown: draft.content,
        isUserEdited: true,
      });
      syncNoteRecord(updated, "已保存");
      return true;
    } catch (error) {
      const info = getErrorInfo(error);
      setDraftStatus(knowledgePointId, "保存失败", info.message);
      toast.error(`笔记保存失败: ${info.message}`);
      return false;
    }
  },

  requestAgentDraft: async (knowledgePointId, userId, context, attemptId) => {
    const { notesByKnowledgePointId, setDraftStatus } = get();
    const note = notesByKnowledgePointId[knowledgePointId];
    if (!note) return;
    set((state) => ({ assistBusy: { ...state.assistBusy, [knowledgePointId]: true } }));
    try {
      const updated = await requestNoteAgentDraft({
        noteId: note.id,
        userId,
        style: "concise",
        focus: "mistake_summary",
        source: { sessionId: context?.sessionId, attemptId },
      });
      set((state) => ({
        notesByKnowledgePointId: { ...state.notesByKnowledgePointId, [knowledgePointId]: updated },
        notesList: sortByUpdatedAt(upsertNote(state.notesList, updated)),
      }));
      toast.success("Agent 辅助补全完成");
    } catch (error) {
      const info = getErrorInfo(error);
      setDraftStatus(knowledgePointId, "保存失败", info.message);
      toast.error(`辅助补全失败: ${info.message}`);
    } finally {
      set((state) => ({ assistBusy: { ...state.assistBusy, [knowledgePointId]: false } }));
    }
  },

  reset: () => {
    set({
      loadState: "idle",
      errorMessage: null,
      notesList: [],
      notesByKnowledgePointId: {},
      noteDrafts: {},
      assistBusy: {},
      drawerOpen: false,
      drawerContext: null,
      reviewNoteContext: null,
      pageSelection: null,
    });
  },
}));

export type { NoteDraftState };
