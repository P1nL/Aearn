import { useCallback, useEffect, useRef, useState } from "react";

import { buildOnboardingMessageSSEUrl, confirmOnboardingPlan, createUser } from "../api";
import type { ApiHealthState, ConversationMessage } from "../appTypes";
import { AssistantUIThread } from "../components/AssistantUIThread";
import { useSSE } from "../hooks/useSSE";
import type { SSEToolCall } from "../hooks/useSSE";
import { createMessage } from "../lib/learningHelpers";
import { useAppStore } from "../stores/useAppStore";
import type { CreatedPlanResponse, UserProfile } from "../types";

type OnboardingPageProps = {
  apiHealth: ApiHealthState;
  existingUser: UserProfile | null;
  resetNonce: number;
  onUserChange: (user: UserProfile) => void;
  onPlanCreated: (plan: CreatedPlanResponse, user: UserProfile) => Promise<void> | void;
};

type OnboardingStreamRequest = {
  endpoint: string;
  requestId: string;
  assistantMessageId: string;
  body: {
    role: "user";
    content: string;
    client_message_id: string;
    user_id?: string;
    onboarding_session_id?: string;
  };
};

const WELCOME_MESSAGE_TEXT = "你好！我是 Aearn 学习助手。想学什么编程语言或技术？告诉我你的目标，我来帮你制定学习计划。";

export function OnboardingPage({
  apiHealth,
  existingUser,
  resetNonce,
  onUserChange,
  onPlanCreated,
}: OnboardingPageProps) {
  const store = useAppStore();
  const onboardingMessages = store.onboardingMessages;
  const onboardingSessionId = store.onboardingSessionId;

  const [streamRequest, setStreamRequest] = useState<OnboardingStreamRequest | null>(null);
  const [preparingMessage, setPreparingMessage] = useState(false);
  const [confirmingPlan, setConfirmingPlan] = useState(false);
  const [displayName] = useState("Pinking");
  const conversationScrollRef = useRef<HTMLElement | null>(null);

  const isStreaming = streamRequest !== null || preparingMessage;

  useEffect(() => {
    if (useAppStore.getState().onboardingMessages.length === 0) {
      store.addOnboardingMessage(createMessage("agent", WELCOME_MESSAGE_TEXT, "Agent"));
    }
  }, [resetNonce]);

  // Auto-scroll on new messages
  useEffect(() => {
    const scrollContainer = conversationScrollRef.current;
    if (!scrollContainer) return;
    const frame = window.requestAnimationFrame(() => {
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [onboardingMessages.length]);

  // SSE streaming for onboarding messages
  useSSE(streamRequest?.endpoint ?? null, {
    method: "POST",
    body: streamRequest?.body,
    requestId: streamRequest?.requestId,
    onEvent: (streamEvent) => {
      if (!streamRequest) return;
      if (streamEvent.type === "agent_message") {
        const incomingText = streamEvent.data.content || streamEvent.data.delta;
        store.updateOnboardingMessage(streamRequest.assistantMessageId, {
          text: streamEvent.data.content ? incomingText : undefined,
          appendText: streamEvent.data.content ? undefined : incomingText,
          status: "streaming",
          statusText: "正在生成……",
        });
      }
      if (streamEvent.type === "session_created") {
        store.setOnboardingSessionId(streamEvent.data.onboarding_session_id);
      }
      if (streamEvent.type === "tool_call") {
        handleToolCallEvent(streamRequest.assistantMessageId, streamEvent.data);
      }
    },
    onDone: () => {
      if (!streamRequest) return;
      store.updateOnboardingMessage(streamRequest.assistantMessageId, {
        status: "done",
        statusText: undefined,
      });
      setStreamRequest(null);
    },
    onError: (error) => {
      if (!streamRequest) return;
      store.updateOnboardingMessage(streamRequest.assistantMessageId, {
        text: `对话出错：${error.code}。${error.message}`,
        status: "error",
        statusText: "可以修改问题后重试。",
      });
      setStreamRequest(null);
    },
  });

  function handleToolCallEvent(messageId: string, payload: SSEToolCall) {
    if (payload.phase === "start") {
      store.startOnboardingToolCall(messageId, payload.tool_call_id, payload.name);
      return;
    }
    if (payload.phase === "delta") {
      store.appendOnboardingToolCallDelta(
        messageId,
        payload.tool_call_id,
        payload.arguments_delta,
      );
      return;
    }
    if (payload.phase === "done") {
      store.finalizeOnboardingToolCall(messageId, payload.tool_call_id, payload.arguments);
    }
  }

  async function ensureUser(): Promise<UserProfile> {
    if (existingUser) return existingUser;
    const created = await createUser(displayName.trim());
    onUserChange(created);
    return created;
  }

  async function handleComposerSubmit(content: string) {
    const trimmed = content.trim();
    if (trimmed.length === 0 || isStreaming) return;

    const assistantMessage: ConversationMessage = {
      ...createMessage("agent", "", "Agent"),
      status: "streaming",
      statusText: "正在连接模型……",
    };

    store.addOnboardingMessage(createMessage("user", trimmed));
    store.addOnboardingMessage(assistantMessage);

    setPreparingMessage(true);
    let activeUser: UserProfile;
    try {
      activeUser = await ensureUser();
    } catch (error) {
      store.updateOnboardingMessage(assistantMessage.id, {
        text: `建档准备失败：${error instanceof Error ? error.message : "未知错误"}。请稍后重试。`,
        status: "error",
        statusText: "本轮消息尚未发送到 Agent。",
      });
      setPreparingMessage(false);
      return;
    }

    setStreamRequest({
      endpoint: buildOnboardingMessageSSEUrl(),
      requestId: createClientId("desktop_onboarding_req"),
      assistantMessageId: assistantMessage.id,
      body: {
        role: "user",
        content: trimmed,
        client_message_id: createClientId("desktop_onboarding_msg"),
        user_id: activeUser.id,
        ...(onboardingSessionId ? { onboarding_session_id: onboardingSessionId } : {}),
      },
    });
    setPreparingMessage(false);
  }

  const handleConfirmPlan = useCallback(async () => {
    if (confirmingPlan) return;
    if (!onboardingSessionId) {
      store.addOnboardingMessage(
        createMessage("agent", "暂时还没有可确认的学习计划，请先完成对话。", "Agent"),
      );
      return;
    }
    setConfirmingPlan(true);
    try {
      const activeUser = await ensureUser();
      const response = await confirmOnboardingPlan(onboardingSessionId, activeUser.id);
      store.addOnboardingMessage(
        createMessage("agent", "学习计划已确认！正在为你准备第一个学习会话……", "Agent"),
      );
      await onPlanCreated(response, activeUser);
    } catch (error) {
      store.addOnboardingMessage(
        createMessage("agent", `确认计划时出错：${error instanceof Error ? error.message : "未知错误"}。请重试。`, "Agent"),
      );
    } finally {
      setConfirmingPlan(false);
    }
  }, [confirmingPlan, onboardingSessionId, existingUser, onPlanCreated]);

  // Bridge the latest route card action to onboarding confirmation.
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ action: string }>).detail;
      if (!detail) return;
      if (detail.action === "start_next") {
        void handleConfirmPlan();
      }
    };
    window.addEventListener("aearn:learning-route-action", handler as EventListener);
    return () =>
      window.removeEventListener("aearn:learning-route-action", handler as EventListener);
  }, [handleConfirmPlan]);

  const sessionActive = apiHealth.status === "online";

  return (
    <div className="onboarding-chat-layout">
      <section className="conversation" aria-label="建档对话" ref={conversationScrollRef}>
        <div className="thread">
          <AssistantUIThread
            messages={onboardingMessages}
            isStreaming={isStreaming}
            sessionActive={sessionActive}
            onSend={handleComposerSubmit}
            placeholder={
              isStreaming
                ? "AI 正在回复……"
                : !sessionActive
                  ? "等待 API 连接后即可开始对话。"
                  : "描述你想学的内容、目标或时间安排……"
            }
            ariaLabel="建档输入框"
            guidanceText={apiHealth.status !== "online" ? "等待 API 连接后即可开始对话。" : undefined}
          />
          {confirmingPlan && (
            <p className="onboarding-confirm-status" role="status">
              正在确认学习计划……
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function createClientId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `${prefix}_${uuid}` : `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}
