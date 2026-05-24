import { useCallback, useEffect, useRef, useState } from "react";

import { buildOnboardingMessageSSEUrl, confirmPlan, createUser } from "../api";
import type { ApiHealthState, ConversationMessage } from "../appTypes";
import { AssistantThread } from "../components/AssistantThread";
import { InlinePlanCard } from "../components/InlinePlanCard";
import { LearningComposer } from "../components/LearningComposer";
import { useSSE } from "../hooks/useSSE";
import type { SSEPlanDraft } from "../hooks/useSSE";
import { createMessage } from "../lib/learningHelpers";
import { useAppStore } from "../stores/useAppStore";
import type { CreatedPlanResponse, LanguageCourse, PlanDraft, UserProfile } from "../types";

type OnboardingPageProps = {
  apiHealth: ApiHealthState;
  courses: LanguageCourse[];
  existingUser: UserProfile | null;
  messages: ConversationMessage[];
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
  };
};

const WELCOME_MESSAGE_TEXT = "你好！我是 Aearn 学习助手。想学什么编程语言或技术？告诉我你的目标，我来帮你制定学习计划。";
const ONBOARDING_QUICK_REPLIES = ["学 Python 基础", "学 JavaScript 前端", "学 HTML/CSS 网页"];

export function OnboardingPage({
  apiHealth,
  courses,
  existingUser,
  resetNonce,
  onUserChange,
  onPlanCreated,
}: OnboardingPageProps) {
  const store = useAppStore();
  const onboardingMessages = store.onboardingMessages;
  const onboardingPlanDraft = store.onboardingPlanDraft;

  const [composerInput, setComposerInput] = useState("");
  const [streamRequest, setStreamRequest] = useState<OnboardingStreamRequest | null>(null);
  const [confirmingPlan, setConfirmingPlan] = useState(false);
  const [displayName] = useState("Pinking");
  const conversationScrollRef = useRef<HTMLElement | null>(null);

  const isStreaming = streamRequest !== null;

  // Show welcome message on mount (if no existing messages)
  useEffect(() => {
    if (onboardingMessages.length === 0) {
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
      if (streamEvent.type === "plan_draft") {
        store.setOnboardingPlanDraft(streamEvent.data as SSEPlanDraft);
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

  async function ensureUser(): Promise<UserProfile> {
    if (existingUser) return existingUser;
    const created = await createUser(displayName.trim());
    onUserChange(created);
    return created;
  }

  function handleComposerSubmit() {
    const content = composerInput.trim();
    if (content.length === 0 || isStreaming) return;

    const assistantMessage: ConversationMessage = {
      ...createMessage("agent", "", "Agent"),
      status: "streaming",
      statusText: "正在连接模型……",
    };

    store.addOnboardingMessage(createMessage("user", content));
    store.addOnboardingMessage(assistantMessage);

    const userId = existingUser?.id;

    setStreamRequest({
      endpoint: buildOnboardingMessageSSEUrl(),
      requestId: createClientId("desktop_onboarding_req"),
      assistantMessageId: assistantMessage.id,
      body: {
        role: "user",
        content,
        client_message_id: createClientId("desktop_onboarding_msg"),
        ...(userId ? { user_id: userId } : {}),
      },
    });
    setComposerInput("");
  }

  async function handleConfirmPlan() {
    if (!onboardingPlanDraft || confirmingPlan) return;
    setConfirmingPlan(true);
    try {
      const activeUser = await ensureUser();
      // Build a PlanDraft-compatible object from the SSE plan_draft data
      // The backend confirmPlan expects the full PlanDraft; the SSE event
      // carries a summary. We pass the draft_id so the backend can look it up.
      const planDraftPayload = {
        draft_id: onboardingPlanDraft.draft_id,
      } as unknown as PlanDraft;

      const response = await confirmPlan(activeUser.id, planDraftPayload);
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
  }

  function handleRevisePlan() {
    // User wants to revise - just send a message asking for changes
    setComposerInput("我想调整这个计划，");
  }

  // Render inline plan card after the message that triggered it
  const renderInlineCard = useCallback(
    (message: ConversationMessage) => {
      // Show plan card after the last agent message when a draft exists
      if (!onboardingPlanDraft) return null;
      const lastAgentMsg = [...onboardingMessages].reverse().find((m) => m.speaker === "agent" && m.status !== "streaming");
      if (message.id !== lastAgentMsg?.id) return null;
      return (
        <InlinePlanCard
          draft={onboardingPlanDraft}
          confirming={confirmingPlan}
          onConfirm={() => void handleConfirmPlan()}
          onRevise={handleRevisePlan}
        />
      );
    },
    [onboardingPlanDraft, confirmingPlan, onboardingMessages],
  );

  const sessionActive = apiHealth.status === "online";

  return (
    <div className="onboarding-chat-layout">
      <section className="conversation" aria-label="建档对话" ref={conversationScrollRef}>
        <div className="thread">
          <AssistantThread
            messages={onboardingMessages}
            renderInlineCard={renderInlineCard}
          />
        </div>
      </section>

      <LearningComposer
        value={composerInput}
        onChange={setComposerInput}
        onSubmit={handleComposerSubmit}
        disabled={isStreaming}
        streaming={isStreaming}
        sessionActive={sessionActive}
        hideNoteButton
        quickReplies={onboardingMessages.length <= 1 ? ONBOARDING_QUICK_REPLIES : undefined}
        placeholder={isStreaming ? "AI 正在回复……" : "描述你想学的内容、目标或时间安排……"}
        ariaLabel="建档输入框"
        guidanceText={apiHealth.status !== "online" ? "等待 API 连接后即可开始对话。" : undefined}
      />
    </div>
  );
}

function createClientId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `${prefix}_${uuid}` : `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}
