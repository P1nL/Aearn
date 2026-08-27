import { useCallback, useEffect, useRef, useState } from "react";

import { fetchTeachingSessions, mutateTeachingSession, openTeachingSession } from "../../api";
import { getErrorInfo } from "../../lib/errorMessages";
import type {
  TeachingActionDescriptor,
  TeachingControlKey,
  TeachingSessionGroupProjection,
  TeachingSessionMode,
  TeachingSessionProjection,
} from "../../types";

export type TeachingAuthorityInput = {
  userId: string;
  trackId: string;
  conversationId: string;
  knowledgeKey: string;
  trackVersion: number;
  progressVersion: number;
  assignmentVersion: number;
};

type TeachingControllerStatus = "idle" | "loading" | "ready" | "error";

type TeachingControllerOptions = {
  onConflictRefresh?: () => Promise<void> | void;
  onTransition?: (session: TeachingSessionProjection) => void;
  onNavigationAction?: (descriptor: TeachingActionDescriptor) => void;
};

export function useTeachingWorkspaceController(options: TeachingControllerOptions = {}) {
  const { onConflictRefresh, onTransition, onNavigationAction } = options;
  const [status, setStatus] = useState<TeachingControllerStatus>("idle");
  const [session, setSession] = useState<TeachingSessionProjection | null>(null);
  const [groups, setGroups] = useState<TeachingSessionGroupProjection[]>([]);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const authorityRef = useRef<TeachingAuthorityInput | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const requestGenerationRef = useRef(0);

  const refreshGroups = useCallback(async (authority: TeachingAuthorityInput, signal?: AbortSignal) => {
    const response = await fetchTeachingSessions(authority.userId, authority.trackId, signal);
    if (signal?.aborted) return;
    setGroups(response.items.map((item) => ({ ...item, turn_ids: [] })));
  }, []);

  const open = useCallback(async (authority: TeachingAuthorityInput) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    authorityRef.current = authority;
    const generation = ++requestGenerationRef.current;
    setStatus("loading");
    setError(null);
    try {
      const response = await openTeachingSession({
        userId: authority.userId,
        trackId: authority.trackId,
        knowledgeKey: authority.knowledgeKey,
        conversationId: authority.conversationId,
        expectedTrackVersion: authority.trackVersion,
        expectedProgressVersion: authority.progressVersion,
        expectedAssignmentVersion: authority.assignmentVersion,
        mode: "guided",
        clientActionId: createTeachingActionId(`teaching-open:${authority.trackId}:${authority.knowledgeKey}`),
        signal: controller.signal,
      });
      if (controller.signal.aborted || generation !== requestGenerationRef.current) return null;
      setSession(response.teaching_session);
      setStatus("ready");
      await refreshGroups(authority, controller.signal);
      return response.teaching_session;
    } catch (caught) {
      if (controller.signal.aborted || generation !== requestGenerationRef.current) return null;
      const info = getErrorInfo(caught);
      setError({ code: info.code, message: info.message });
      setStatus("error");
      return null;
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, [refreshGroups]);

  const refresh = useCallback(async () => {
    const authority = authorityRef.current;
    if (!authority) return null;
    return open(authority);
  }, [open]);

  const runMutation = useCallback(async (
    key: string,
    controlKey: TeachingControlKey,
    descriptor?: TeachingActionDescriptor,
    targetMode?: TeachingSessionMode,
    targetKnowledgeKey?: string,
  ) => {
    const authority = authorityRef.current;
    const current = session;
    if (!authority || !current || pendingActionKey) return null;
    const versions = descriptor?.expected_versions ?? {
      session: current.session_version,
      track: current.track_version,
      progress: current.progress_version,
      assignment: current.assignment_version,
    };
    if (!versions.session || !versions.track || !versions.progress || !versions.assignment) {
      setError({ code: "TEACHING_ACTION_INVALID", message: "服务端 action descriptor 缺少完整 authority version。" });
      return null;
    }
    const controller = new AbortController();
    requestRef.current?.abort();
    requestRef.current = controller;
    setPendingActionKey(key);
    setError(null);
    try {
      const response = await mutateTeachingSession({
        userId: authority.userId,
        trackId: authority.trackId,
        sessionId: current.session_id,
        controlKey,
        expectedSessionVersion: versions.session,
        expectedTrackVersion: versions.track,
        expectedProgressVersion: versions.progress,
        expectedAssignmentVersion: versions.assignment,
        ...(targetMode ? { targetMode } : {}),
        ...(targetKnowledgeKey ? { targetKnowledgeKey } : {}),
        clientActionId: createTeachingActionId(`teaching-${key}`),
        signal: controller.signal,
      });
      if (controller.signal.aborted) return null;
      const next = response.next_teaching_session ?? response.teaching_session;
      setSession(next);
      setStatus("ready");
      await refreshGroups({ ...authority, knowledgeKey: next.knowledge_key, trackVersion: next.track_version, progressVersion: next.progress_version, assignmentVersion: next.assignment_version }, controller.signal);
      if (response.next_teaching_session) onTransition?.(response.next_teaching_session);
      return response;
    } catch (caught) {
      if (controller.signal.aborted) return null;
      const info = getErrorInfo(caught);
      setError({ code: info.code, message: info.message });
      if (isTeachingConflict(info.code)) {
        if (onConflictRefresh) await onConflictRefresh();
        else await refresh();
      }
      return null;
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
      setPendingActionKey(null);
    }
  }, [onConflictRefresh, onTransition, pendingActionKey, refresh, refreshGroups, session]);

  const switchMode = useCallback(async () => {
    if (!session) return null;
    if (session.mode === "guided") {
      return runMutation("switch-mode", "switch_mode", undefined, "free_reading");
    }
    return runMutation("escalate-guided", "escalate_guided");
  }, [runMutation, session]);

  const performAction = useCallback(async (descriptor: TeachingActionDescriptor) => {
    if (!descriptor.enabled || pendingActionKey) return null;
    if (descriptor.target_kind === "navigation" || descriptor.target_kind === "artifact") {
      if (descriptor.key === "refresh_session") return refresh();
      onNavigationAction?.(descriptor);
      return null;
    }
    if (!isTeachingControlKey(descriptor.key)) {
      setError({ code: "TEACHING_ACTION_INVALID", message: "服务端返回了 Desktop 不支持的 teaching control。" });
      return null;
    }
    return runMutation(
      descriptor.key,
      descriptor.key,
      descriptor,
      descriptor.key === "switch_mode" && isTeachingSessionMode(descriptor.target_id) ? descriptor.target_id : undefined,
      descriptor.key === "enter_next_knowledge" ? descriptor.target_id ?? undefined : undefined,
    );
  }, [onNavigationAction, pendingActionKey, refresh, runMutation]);

  useEffect(() => () => requestRef.current?.abort(), []);

  return { status, session, groups, pendingActionKey, error, open, refresh, switchMode, performAction };
}

function isTeachingConflict(code: string): boolean {
  return code === "TEACHING_SESSION_CONFLICT" || code === "CONFLICT" || code.endsWith("_STALE");
}

function isTeachingSessionMode(value: string | null): value is TeachingSessionMode {
  return value === "guided" || value === "free_reading";
}

function isTeachingControlKey(value: string): value is TeachingControlKey {
  return ["open_session", "continue", "return_focus", "change_example", "escalate_guided", "switch_mode", "pause", "resume", "enter_next_knowledge"].includes(value);
}

function createTeachingActionId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}:${random}`;
}
