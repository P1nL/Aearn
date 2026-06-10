import { startTransition, useEffect, useRef, useState } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

import { buildReviewMessageSSEUrl, fetchReviewMessages, fetchTodayReviews, runLearningExercise, startReviewSession, submitReviewExerciseResult, submitReviewWarmupResult } from "../api";
import type { AsyncActionState, ConversationMessage, ExerciseRunMode, NoteContext } from "../appTypes";
import { AssistantUIThread } from "../components/AssistantUIThread";
import { CodeEditor } from "../features/learning/CodeEditor";
import { RuntimeFeedback } from "../features/learning/RuntimeFeedback";
import { useSSE } from "../hooks/useSSE";
import { completionResultLabel, fsrsRatingLabel, runtimeLabel, runtimeStatusLabel } from "../lib/desktopLabels";
import { formatErrorMessage } from "../lib/errorMessages";
import { createMessage, toActionError } from "../lib/learningHelpers";
import { isRecord } from "../lib/typeGuards";
import { useAppStore } from "../stores/useAppStore";
import type {
  CodeCompletionResult,
  LearningExercise,
  ReviewDueItem,
  ReviewHistoryMessage,
  ReviewAiPatchAnswer,
  ReviewExerciseResultResponse,
  ReviewSessionResponse,
  ReviewWarmupResultResponse,
  RunExerciseResponse,
  UserProfile,
} from "../types";

type ReviewPageProps = {
  isActive: boolean;
  user: UserProfile | null;
  selectedKnowledgePointId: string | null;
  messages: ConversationMessage[];
  onActiveKnowledgePointChange: (knowledgePointId: string | null) => void;
  onActiveNoteContextChange: (context: NoteContext | null) => void;
};

type ReviewStreamRequest = {
  endpoint: string;
  requestId: string;
  assistantMessageId: string;
  body: {
    user_id: string;
    role: "user";
    content: string;
    client_message_id: string;
  };
};

type ReviewWarmupUiState = "idle" | "submitting" | "error";
type ReviewSubmitUiState = "idle" | "submitting" | "done" | "error";

type ReviewSessionCacheEntry = {
  review: ReviewSessionResponse;
  messages: ConversationMessage[];
  editorCode: string;
  filledBlanks: Record<string, string>;
  explanation: string;
  warmupAnswer: string;
  warmupState: ReviewWarmupUiState;
  reviewPatchAnswer: ReviewAiPatchAnswer;
  submitState: ReviewSubmitUiState;
  reviewResult: ReviewExerciseResultResponse | null;
  reviewRun: RunExerciseResponse | null;
  reviewRunMode: ExerciseRunMode | null;
  reviewRunState: AsyncActionState;
  reviewRunIsStale: boolean;
  activeExerciseCardId: string | null;
  reviewCardResults: Record<string, ReviewCompletedExerciseCardState | null>;
};

type ReviewCompletedExerciseCardState = {
  exercise: LearningExercise | null;
  result: ReviewExerciseResultResponse | null;
  editorCode: string;
  filledBlanks: Record<string, string>;
  explanation: string;
  patchAnswer: ReviewAiPatchAnswer;
  variantReason: string;
};

type PreparedReviewConversation = {
  messages: ConversationMessage[];
  activeExerciseCardId: string | null;
  reviewCardResults: Record<string, ReviewCompletedExerciseCardState | null>;
};

export function ReviewPage({
  isActive,
  user,
  selectedKnowledgePointId,
  messages,
  onActiveKnowledgePointChange,
  onActiveNoteContextChange,
}: ReviewPageProps) {
  const store = useAppStore();
  const [dueItems, setDueItems] = useState<ReviewDueItem[]>([]);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activeReview, setActiveReview] = useState<ReviewSessionResponse | null>(null);
  const [editorCode, setEditorCode] = useState("");
  const [filledBlanks, setFilledBlanks] = useState<Record<string, string>>({});
  const [explanation, setExplanation] = useState("");
  const [warmupAnswer, setWarmupAnswer] = useState("");
  const [warmupState, setWarmupState] = useState<ReviewWarmupUiState>("idle");
  const [startingKnowledgePointId, setStartingKnowledgePointId] = useState<string | null>(null);
  const [startRequestedKnowledgePointId, setStartRequestedKnowledgePointId] = useState<string | null>(null);
  const [reviewPatchAnswer, setReviewPatchAnswer] = useState<ReviewAiPatchAnswer>({
    verdict: "fail",
    evidence: "",
    knowledge_point_risk: "",
    next_action: "request_change",
  });
  const [submitState, setSubmitState] = useState<ReviewSubmitUiState>("idle");
  const [reviewResult, setReviewResult] = useState<ReviewExerciseResultResponse | null>(null);
  const [reviewRun, setReviewRun] = useState<RunExerciseResponse | null>(null);
  const [reviewRunMode, setReviewRunMode] = useState<ExerciseRunMode | null>(null);
  const [reviewRunState, setReviewRunState] = useState<AsyncActionState>({ status: "idle" });
  const [reviewRunIsStale, setReviewRunIsStale] = useState(false);
  const [activeExerciseCardId, setActiveExerciseCardId] = useState<string | null>(null);
  const [reviewCardResults, setReviewCardResults] = useState<Record<string, ReviewCompletedExerciseCardState | null>>({});
  const [streamRequest, setStreamRequest] = useState<ReviewStreamRequest | null>(null);
  const conversationScrollRef = useRef<HTMLElement | null>(null);
  const reviewSessionCacheRef = useRef<Record<string, ReviewSessionCacheEntry>>({});
  const latestStartRequestIdRef = useRef(0);
  const selectedKnowledgePointIdRef = useRef<string | null>(selectedKnowledgePointId);
  const isActiveRef = useRef(isActive);

  const isStreaming = streamRequest !== null;

  useEffect(() => {
    selectedKnowledgePointIdRef.current = selectedKnowledgePointId;
  }, [selectedKnowledgePointId]);

  useEffect(() => {
    isActiveRef.current = isActive;
  }, [isActive]);

  useEffect(() => {
    reviewSessionCacheRef.current = {};
  }, [user?.id]);

  // SSE streaming for review messages
  useSSE(streamRequest?.endpoint ?? null, {
    method: "POST",
    body: streamRequest?.body,
    requestId: streamRequest?.requestId,
    onEvent: (streamEvent) => {
      if (!streamRequest || streamEvent.type !== "agent_message") return;
      const incomingText = streamEvent.data.content || streamEvent.data.delta;
      store.updateReviewMessage(streamRequest.assistantMessageId, {
        text: streamEvent.data.content ? incomingText : undefined,
        appendText: streamEvent.data.content ? undefined : incomingText,
        status: "streaming",
        statusText: "正在生成……",
      });
    },
    onDone: () => {
      if (!streamRequest) return;
      store.updateReviewMessage(streamRequest.assistantMessageId, {
        status: "done",
        statusText: undefined,
      });
      setStreamRequest(null);
    },
    onError: (error) => {
      if (!streamRequest) return;
      store.updateReviewMessage(streamRequest.assistantMessageId, {
        text: `回复出错：${error.code}。${error.message}`,
        status: "error",
        statusText: "可以修改问题后重试。",
      });
      setStreamRequest(null);
    },
  });

  // Auto-scroll on new messages
  useEffect(() => {
    const scrollContainer = conversationScrollRef.current;
    if (!scrollContainer) return;
    const frame = window.requestAnimationFrame(() => {
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [messages.length, activeReview?.session_id, reviewResult?.attempt_id]);

  useEffect(() => {
    cacheActiveReviewSnapshot();
  }, [
    activeReview,
    messages,
    editorCode,
    filledBlanks,
    explanation,
    warmupAnswer,
    warmupState,
    reviewPatchAnswer,
    submitState,
    reviewResult,
    reviewRun,
    reviewRunMode,
    reviewRunState,
    reviewRunIsStale,
    activeExerciseCardId,
    reviewCardResults,
  ]);

  function handleComposerSubmit(input: string) {
    const content = input.trim();
    if (content.length === 0 || isStreaming || warmupState === "submitting" || !activeReview || !user) return;

    if (warmupPending) {
      store.addReviewMessage(createMessage("user", content));
      void handleWarmupSubmit(isWarmupSkipIntent(content) ? "skip" : "answer", content);
      return;
    }

    const assistantMessage: ConversationMessage = {
      ...createMessage("agent", "", "Agent"),
      status: "streaming",
      statusText: "正在连接模型……",
    };

    store.addReviewMessage(createMessage("user", content));
    store.addReviewMessage(assistantMessage);

    setStreamRequest({
      endpoint: buildReviewMessageSSEUrl(activeReview.session_id),
      requestId: createClientId("desktop_review_req"),
      assistantMessageId: assistantMessage.id,
      body: {
        user_id: user.id,
        role: "user",
        content,
        client_message_id: createClientId("desktop_review_msg"),
      },
    });
  }

  async function loadDueReviews(signal?: AbortSignal) {
    if (!user) {
      setDueItems([]);
      setLoadState("idle");
      return;
    }
    setLoadState("loading");
    setErrorMessage(null);
    try {
      const response = await fetchTodayReviews(user.id, signal);
      startTransition(() => {
        setDueItems(response.items);
        setLoadState("ready");
      });
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      setLoadState("error");
      setErrorMessage(formatErrorMessage(error, "无法加载今日复习"));
    }
  }

  function cacheActiveReviewSnapshot() {
    if (!activeReview) {
      return;
    }
    reviewSessionCacheRef.current[activeReview.knowledge_point.id] = {
      review: activeReview,
      messages: [...messages],
      editorCode,
      filledBlanks: { ...filledBlanks },
      explanation,
      warmupAnswer,
      warmupState: warmupState === "submitting" ? "idle" : warmupState,
      reviewPatchAnswer: { ...reviewPatchAnswer },
      submitState: submitState === "submitting" ? "idle" : submitState,
      reviewResult,
      reviewRun,
      reviewRunMode,
      reviewRunState: reviewRunState.status === "loading" ? { status: "idle" } : reviewRunState,
      reviewRunIsStale,
      activeExerciseCardId,
      reviewCardResults: { ...reviewCardResults },
    };
  }

  function initialReviewCacheEntry(review: ReviewSessionResponse, restoredMessages: ConversationMessage[]): ReviewSessionCacheEntry {
    const prepared = prepareReviewConversationMessages(review, restoredMessages);
    return {
      review,
      messages: prepared.messages,
      editorCode: review.review_exercise.starter_code,
      filledBlanks: defaultFilledBlanks(review),
      explanation: "",
      warmupAnswer: review.warmup.last_answer ?? "",
      warmupState: "idle",
      reviewPatchAnswer: defaultReviewPatchAnswer(),
      submitState: "idle",
      reviewResult: null,
      reviewRun: null,
      reviewRunMode: null,
      reviewRunState: { status: "idle" },
      reviewRunIsStale: false,
      activeExerciseCardId: prepared.activeExerciseCardId,
      reviewCardResults: prepared.reviewCardResults,
    };
  }

  function applyReviewCacheEntry(entry: ReviewSessionCacheEntry) {
    setActiveReview(entry.review);
    setEditorCode(entry.editorCode);
    setFilledBlanks(entry.filledBlanks);
    setExplanation(entry.explanation);
    setWarmupAnswer(entry.warmupAnswer);
    setWarmupState(entry.warmupState);
    setReviewPatchAnswer(entry.reviewPatchAnswer);
    setSubmitState(entry.submitState);
    setReviewResult(entry.reviewResult);
    setReviewRun(entry.reviewRun);
    setReviewRunMode(entry.reviewRunMode);
    setReviewRunState(entry.reviewRunState);
    setReviewRunIsStale(entry.reviewRunIsStale);
    setActiveExerciseCardId(entry.activeExerciseCardId);
    setReviewCardResults(entry.reviewCardResults);
    store.setReviewConversation(entry.messages);
  }

  function restoreCachedReview(knowledgePointId: string) {
    const cached = reviewSessionCacheRef.current[knowledgePointId];
    if (!cached) {
      return false;
    }
    latestStartRequestIdRef.current += 1;
    setStreamRequest(null);
    setStartingKnowledgePointId(null);
    setStartRequestedKnowledgePointId(knowledgePointId);
    setErrorMessage(null);
    applyReviewCacheEntry(cached);
    onActiveKnowledgePointChange(cached.review.knowledge_point.id);
    return true;
  }

  async function handleStartReview(item: ReviewDueItem, options?: { forceRefresh?: boolean }) {
    if (!user) {
      return;
    }
    const requestKnowledgePointId = item.KnowledgePoint.id;
    cacheActiveReviewSnapshot();
    if (!options?.forceRefresh && restoreCachedReview(requestKnowledgePointId)) {
      return;
    }
    const requestId = latestStartRequestIdRef.current + 1;
    latestStartRequestIdRef.current = requestId;
    setStartRequestedKnowledgePointId(requestKnowledgePointId);
    if (activeReview?.knowledge_point.id !== requestKnowledgePointId) {
      setActiveReview(null);
      store.clearReviewConversation();
    }
    setStartingKnowledgePointId(requestKnowledgePointId);
    setSubmitState("idle");
    setWarmupState("idle");
    setReviewResult(null);
    setReviewRun(null);
    setReviewRunMode(null);
    setReviewRunState({ status: "idle" });
    setReviewRunIsStale(false);
    setActiveExerciseCardId(null);
    setReviewCardResults({});
    setErrorMessage(null);
    try {
      const response = await startReviewSession({
        userId: user.id,
        knowledgePointId: requestKnowledgePointId,
      });
      const restoredMessages = await restoreReviewConversationMessages({
        userId: user.id,
        sessionId: response.session_id,
        fallbackReview: response,
      });
      if (
        latestStartRequestIdRef.current !== requestId ||
        selectedKnowledgePointIdRef.current !== requestKnowledgePointId ||
        !isActiveRef.current
      ) {
        return;
      }
      const cacheEntry = initialReviewCacheEntry(response, restoredMessages);
      reviewSessionCacheRef.current[requestKnowledgePointId] = cacheEntry;
      applyReviewCacheEntry(cacheEntry);
      onActiveKnowledgePointChange(response.knowledge_point.id);
    } catch (error) {
      if (
        latestStartRequestIdRef.current === requestId &&
        selectedKnowledgePointIdRef.current === requestKnowledgePointId &&
        isActiveRef.current
      ) {
        setErrorMessage(formatErrorMessage(error, "无法开始复习"));
      }
    } finally {
      if (latestStartRequestIdRef.current === requestId) {
        setStartingKnowledgePointId(null);
      }
    }
  }

  async function handleWarmupSubmit(action: "answer" | "skip", answerOverride?: string) {
    if (!activeReview || !user || warmupState === "submitting") {
      return;
    }
    const submittedAnswer = answerOverride ?? warmupAnswer;
    setWarmupState("submitting");
    setErrorMessage(null);
    try {
      const response = await submitReviewWarmupResult({
        userId: user.id,
        sessionId: activeReview.session_id,
        action,
        answer: action === "skip" ? undefined : submittedAnswer,
      });
      const nextReview: ReviewSessionResponse = {
        ...activeReview,
        review_stage: response.review_stage,
        review_stage_state: response.review_stage_state,
        current_node: response.current_node,
        warmup: response.warmup,
      };
      const exerciseCard = isReviewWarmupPending(response.review_stage) ? null : createReviewExerciseCardMessage(nextReview);
      startTransition(() => {
        setActiveReview(nextReview);
        setWarmupAnswer(response.warmup.last_answer ?? submittedAnswer);
        setWarmupState("idle");
        if (exerciseCard) {
          setActiveExerciseCardId(exerciseCard.id);
          setReviewCardResults((current) => ({ ...current, [exerciseCard.id]: null }));
          setReviewRun(null);
          setReviewRunMode(null);
          setReviewRunState({ status: "idle" });
          setReviewRunIsStale(false);
          setReviewResult(null);
        }
      });
      store.addReviewMessage(createMessage("agent", buildWarmupResultMessage(response), "Agent"));
      if (exerciseCard) {
        store.addReviewMessage(exerciseCard);
      }
    } catch (error) {
      setWarmupState("error");
      setErrorMessage(formatErrorMessage(error, "热身提交失败"));
    }
  }

  async function handleRunReviewExercise(runMode: ExerciseRunMode) {
    if (!activeReview || !user || warmupPending || reviewRunState.status === "loading") {
      return;
    }
    const exercise = activeReview.review_exercise;
    if (exercise.exercise_type === "review_ai_patch") {
      return;
    }
    setReviewRunState({
      status: "loading",
      label: runMode === "preview" ? "正在返回运行预览" : "正在运行可见测试",
    });
    setErrorMessage(null);
    try {
      const response = await runLearningExercise({
        userId: user.id,
        sessionId: activeReview.session_id,
        exerciseId: exercise.id,
        code: buildSubmittedCode(editorCode, filledBlanks),
        filledBlanks,
        runtimeProfileId: exercise.runtime_profile.id,
        runMode,
      });
      startTransition(() => {
        setReviewRun(response);
        setReviewRunMode(runMode);
        setReviewRunState({ status: "idle" });
        setReviewRunIsStale(false);
        setReviewResult(null);
        if (submitState === "error") {
          setSubmitState("idle");
        }
      });
    } catch (error) {
      setReviewRunState(toActionError(error));
    }
  }

  async function handleSubmitReview() {
    if (!activeReview || !user || submitState === "submitting") {
      return;
    }
    const exercise = activeReview.review_exercise;
    const requiresRun = exercise.exercise_type !== "review_ai_patch";
    if (
      requiresRun &&
      (!reviewRun ||
        reviewRunMode !== "visible_tests" ||
        reviewRunIsStale ||
        reviewRun.runtime_status !== "success" ||
        reviewRunState.status === "loading")
    ) {
      return;
    }
    setSubmitState("submitting");
    setErrorMessage(null);
    try {
      const result = await submitReviewExerciseResult({
        userId: user.id,
        sessionId: activeReview.session_id,
        exerciseId: exercise.id,
        attemptId: requiresRun && reviewRun ? reviewRun.attempt_id : undefined,
        code: exercise.exercise_type === "review_ai_patch" ? editorCode || patchOriginalCode(exercise.metadata_json) : buildSubmittedCode(editorCode, filledBlanks),
        filledBlanks: exercise.exercise_type === "review_ai_patch" ? {} : filledBlanks,
        explanation: exercise.exercise_type === "review_ai_patch" ? reviewPatchAnswer.evidence : explanation,
        reviewAiPatchAnswer: exercise.exercise_type === "review_ai_patch" ? reviewPatchAnswer : undefined,
      });
      let nextExerciseCard: ConversationMessage | null = null;
      let nextReviewForCard: ReviewSessionResponse | null = null;
      const completedCardState = completedCardStateFromCurrentReview(activeReview, result, {
        editorCode,
        filledBlanks,
        explanation,
        patchAnswer: reviewPatchAnswer,
      });
      if (result.next_action === "next_exercise" && result.review_exercise && result.review_stage_state && result.current_node) {
        nextReviewForCard = {
          ...activeReview,
          review_exercise: result.review_exercise,
          review_stage: result.review_stage ?? activeReview.review_stage,
          review_stage_state: result.review_stage_state,
          current_node: result.current_node,
          variant_reason: result.review_stage_state.variant.selection_reason ?? activeReview.variant_reason,
        };
        nextExerciseCard = createReviewExerciseCardMessage(nextReviewForCard);
      }
      startTransition(() => {
        setReviewResult(nextExerciseCard ? null : result);
        const nextExercise = result.review_exercise;
        const nextStageState = result.review_stage_state;
        const nextNode = result.current_node;
        const nextReviewState = result.ReviewState;
        const nextKnowledgePoint = result.KnowledgePoint;
        if (nextExerciseCard && nextReviewForCard && nextExercise && nextStageState && nextNode) {
          setActiveReview(nextReviewForCard);
          setEditorCode(nextExercise.starter_code);
          setFilledBlanks(defaultFilledBlanksForExercise(nextExercise));
          setExplanation("");
          setReviewPatchAnswer(defaultReviewPatchAnswer());
          setSubmitState("idle");
          setActiveExerciseCardId(nextExerciseCard.id);
          setReviewRun(null);
          setReviewRunMode(null);
          setReviewRunState({ status: "idle" });
          setReviewRunIsStale(false);
          setReviewCardResults((current) => ({
            ...current,
            ...(activeExerciseCardId ? { [activeExerciseCardId]: completedCardState } : {}),
            [nextExerciseCard.id]: null,
          }));
        } else if (result.next_action === "schedule_review" && nextReviewState && nextKnowledgePoint) {
          setActiveReview((current) =>
            current
              ? {
                  ...current,
                  review_stage: "final_summary",
                  review_stage_state: result.review_stage_state ?? current.review_stage_state,
                  current_node: result.current_node ?? current.current_node,
                  ReviewState: nextReviewState,
                  knowledge_point: {
                    ...current.knowledge_point,
                    status: nextKnowledgePoint.status,
                  },
                }
              : current,
          );
          setSubmitState("done");
          setReviewCardResults((current) => ({
            ...current,
            ...(activeExerciseCardId ? { [activeExerciseCardId]: completedCardState } : {}),
          }));
          void loadDueReviews();
        } else {
          setReviewCardResults((current) => ({
            ...current,
            ...(activeExerciseCardId ? { [activeExerciseCardId]: completedCardState } : {}),
          }));
          setSubmitState("idle");
        }
      });
      if (nextExerciseCard) {
        store.addReviewMessage(nextExerciseCard);
      }
    } catch (error) {
      setSubmitState("error");
      setErrorMessage(formatErrorMessage(error, "复习提交失败"));
    }
  }

  useEffect(() => {
    if (!isActive) {
      onActiveNoteContextChange(null);
      return;
    }
    const controller = new AbortController();
    void loadDueReviews(controller.signal);
    return () => controller.abort();
  }, [isActive, user?.id]);

  useEffect(() => {
    if (!isActive) {
      return;
    }
    setErrorMessage(null);
    setReviewResult(null);
    setStartRequestedKnowledgePointId(null);
    if (!selectedKnowledgePointId) {
      setActiveReview(null);
      store.clearReviewConversation();
      onActiveNoteContextChange(null);
    }
  }, [isActive, selectedKnowledgePointId, user?.id]);

  useEffect(() => {
    if (!isActive || !user || !selectedKnowledgePointId || loadState !== "ready" || startingKnowledgePointId) {
      return;
    }
    if (activeReview?.knowledge_point.id === selectedKnowledgePointId) {
      return;
    }
    if (startRequestedKnowledgePointId === selectedKnowledgePointId) {
      return;
    }

    const targetItem = dueItems.find((item) => item.KnowledgePoint.id === selectedKnowledgePointId);
    if (!targetItem) {
      setErrorMessage("这个知识点当前没有到期复习项；请从左侧选择标记为已到期的复习知识点。");
      return;
    }

    void handleStartReview(targetItem);
  }, [
    activeReview?.knowledge_point.id,
    dueItems,
    isActive,
    loadState,
    selectedKnowledgePointId,
    startRequestedKnowledgePointId,
    startingKnowledgePointId,
    user?.id,
  ]);

  useEffect(() => {
    if (!isActive || !activeReview) {
      onActiveNoteContextChange(null);
      return;
    }
    onActiveNoteContextChange({
      knowledgePointId: activeReview.knowledge_point.id,
      knowledgePointTitle: activeReview.knowledge_point.title,
      source: "review",
      sessionId: activeReview.session_id,
      language: activeReview.review_exercise.runtime_profile.language,
    });
  }, [isActive, activeReview?.session_id, activeReview?.knowledge_point.id]);

  const activeExercise = activeReview?.review_exercise ?? null;
  const isPatchReview = activeExercise?.exercise_type === "review_ai_patch";
  const warmupPending = activeReview?.review_stage === "warmup" || activeReview?.review_stage === "warmup_repair";
  const patchAnswerComplete =
    !isPatchReview ||
    (reviewPatchAnswer.evidence.trim().length > 0 && reviewPatchAnswer.knowledge_point_risk.trim().length > 0);
  const blankValuesComplete =
    !activeExercise ||
    isPatchReview ||
    activeExercise.code_blanks.every((blank) => (filledBlanks[blank.blank_key] ?? "").trim().length > 0);
  const explanationRequired = Boolean(
    activeExercise && !isPatchReview && (activeExercise.requires_explanation || activeExercise.exercise_type === "explain_code"),
  );
  const explanationComplete = !explanationRequired || explanation.trim().length > 0;
  const runRequired = Boolean(activeExercise && !isPatchReview);
  const freshVisibleRunReady =
    !runRequired ||
    (reviewRun !== null &&
      reviewRunMode === "visible_tests" &&
      !reviewRunIsStale &&
      reviewRun.runtime_status === "success");
  const submitNotice = activeExercise
    ? reviewSubmitNotice(activeExercise, submitState, {
        blankValuesComplete,
        explanationRequired,
        explanationComplete,
        patchAnswerComplete,
        runRequired,
        hasRun: reviewRun !== null,
        runMode: reviewRunMode,
        runIsStale: reviewRunIsStale,
        runStatus: reviewRun?.runtime_status ?? null,
        runInFlight: reviewRunState.status === "loading",
      })
    : "";
  const submitDisabled =
    !activeReview ||
    warmupPending ||
    !patchAnswerComplete ||
    !blankValuesComplete ||
    !explanationComplete ||
    !freshVisibleRunReady ||
    reviewRunState.status === "loading" ||
    submitState === "submitting" ||
    submitState === "done";
  const composerSessionActive = Boolean(activeReview);
  const composerBusy = isStreaming || warmupState === "submitting";
  const selectedDueItem = selectedKnowledgePointId ? dueItems.find((item) => item.KnowledgePoint.id === selectedKnowledgePointId) ?? null : null;
  const reviewThreadMessages = activeReview ? messages : [];
  const showReviewSelectionPrompt = loadState === "ready" && dueItems.length > 0 && !selectedKnowledgePointId;
  const reviewLoadingMessage = startingKnowledgePointId ? "正在准备复习材料，首次打开可能需要稍等。" : "正在加载今日复习状态。";
  const showReviewLoading = !activeReview && !errorMessage && (loadState === "loading" || startingKnowledgePointId !== null);
  const showReviewStatus =
    !activeReview &&
    !showReviewLoading &&
    (!user || loadState === "error" || (loadState === "ready" && dueItems.length === 0) || showReviewSelectionPrompt || Boolean(errorMessage));
  const composerAttachmentNode = errorMessage && activeReview ? <div className="tool-card">错误：{errorMessage}</div> : null;

  function renderReviewMessageAttachment(message: ConversationMessage): ReactNode {
    if (message.attachment?.type !== "review_exercise") {
      return null;
    }
    const isActiveCard =
      message.id === activeExerciseCardId &&
      activeReview?.review_exercise.id === message.attachment.exerciseId &&
      activeExercise !== null &&
      !warmupPending;
    if (!isActiveCard || !activeReview) {
      const completedCard = reviewCardResults[message.id] ?? null;
      if (activeReview && completedCard?.exercise && completedCard.result) {
        return (
          <div className="review-tool-exercise">
            <ReviewExerciseWorkbench
              review={reviewForCompletedCard(activeReview, completedCard, completedCard.exercise)}
              result={completedCard.result}
              editorCode={completedCard.editorCode}
              filledBlanks={completedCard.filledBlanks}
              explanation={completedCard.explanation}
              patchAnswer={completedCard.patchAnswer}
              submitDisabled
              submitNotice=""
              submitState="done"
              run={null}
              runMode={null}
              runState={{ status: "idle" }}
              runIsStale={false}
              readOnly
              onCodeChange={() => undefined}
              onBlankChange={() => undefined}
              onExplanationChange={() => undefined}
              onPatchAnswerChange={() => undefined}
              onRunPreview={() => undefined}
              onRunVisibleTests={() => undefined}
              onRetryRun={() => undefined}
              onSubmit={() => undefined}
            />
          </div>
        );
      }
      return (
        <ReviewArchivedExerciseCard
          title={message.attachment.title}
          result={completedCard?.result ?? null}
        />
      );
    }
    return (
      <div className="review-tool-exercise">
        <ReviewExerciseWorkbench
          review={activeReview}
          result={reviewResult}
          editorCode={editorCode}
          filledBlanks={filledBlanks}
          explanation={explanation}
          patchAnswer={reviewPatchAnswer}
          submitDisabled={submitDisabled}
          submitNotice={submitNotice}
          submitState={submitState}
          run={reviewRun}
          runMode={reviewRunMode}
          runState={reviewRunState}
          runIsStale={reviewRunIsStale}
          onCodeChange={(value) => {
            setEditorCode(value);
            if (reviewRun || reviewResult) {
              setReviewRunIsStale(true);
            }
          }}
          onBlankChange={(blankKey, value) => {
            setFilledBlanks((current) => ({
              ...current,
              [blankKey]: value,
            }));
            if (reviewRun || reviewResult) {
              setReviewRunIsStale(true);
            }
          }}
          onExplanationChange={setExplanation}
          onPatchAnswerChange={setReviewPatchAnswer}
          onRunPreview={() => void handleRunReviewExercise("preview")}
          onRunVisibleTests={() => void handleRunReviewExercise("visible_tests")}
          onRetryRun={() => void handleRunReviewExercise(reviewRunMode ?? "visible_tests")}
          onSubmit={() => void handleSubmitReview()}
        />
      </div>
    );
  }

  return (
    <div className="review-screen">
      <div className="review-thread-wrap">
        <section className="conversation" aria-label="复习对话" ref={conversationScrollRef}>
          <div className="thread">
            {activeReview && (
              <>
                <div className="lesson-title">
                  <p>{`当前复习知识点：${activeReview.knowledge_point.title}。热身、变体练习和反馈会留在同一个线程里。`}</p>
                </div>

                <AssistantUIThread
                  messages={reviewThreadMessages}
                  isStreaming={composerBusy}
                  sessionActive={composerSessionActive}
                  onSend={handleComposerSubmit}
                  hideNoteButton
                  placeholder={
                    composerBusy
                      ? warmupState === "submitting" ? "正在记录热身……" : "AI 正在回复……"
                      : warmupPending
                        ? "说一句你的理解，或输入“跳过”。"
                        : "用自己的话复述，或请求提示……"
                  }
                  ariaLabel="复习输入框"
                  renderMessageAttachment={renderReviewMessageAttachment}
                  beforeComposer={composerAttachmentNode}
                />
              </>
            )}

            {showReviewLoading && (
              <div className="review-loading-state" role="status" aria-label="正在加载复习会话">
                <div className="review-loading-card">
                  <div className="wb-spinner" aria-hidden="true" />
                  <p>{reviewLoadingMessage}</p>
                </div>
              </div>
            )}

            {showReviewStatus && (
              <article className="system-card" aria-label="复习状态">
                <h3>复习状态</h3>
                <p>
                  {!user
                    ? "先完成建档和学习计划后，复习页才会加载待复习内容。"
                    : loadState === "ready" && dueItems.length === 0
                        ? "当前没有已到期复习项。"
                        : errorMessage ?? "等待你从左侧选择一个已到期复习知识点。"}
                </p>
                {(errorMessage || (user && loadState === "ready" && dueItems.length === 0)) && (
                  <div className="system-card-actions">
                    <button className="btn ghost-btn" type="button" disabled={!user || loadState === "loading"} onClick={() => void loadDueReviews()}>
                      {loadState === "loading" ? "刷新中..." : "重新加载复习状态"}
                    </button>
                    {selectedDueItem && (
                      <button
                        className="btn primary ghost-btn"
                        type="button"
                        disabled={startingKnowledgePointId === selectedDueItem.KnowledgePoint.id}
                        onClick={() => void handleStartReview(selectedDueItem, { forceRefresh: true })}
                      >
                        {startingKnowledgePointId === selectedDueItem.KnowledgePoint.id ? "生成复习材料..." : "重试开始复习"}
                      </button>
                    )}
                  </div>
                )}
              </article>
            )}

          </div>
        </section>
      </div>
    </div>
  );
}

type ReviewExerciseWorkbenchProps = {
  review: ReviewSessionResponse;
  result: ReviewExerciseResultResponse | null;
  editorCode: string;
  filledBlanks: Record<string, string>;
  explanation: string;
  patchAnswer: ReviewAiPatchAnswer;
  submitDisabled: boolean;
  submitNotice: string;
  submitState: "idle" | "submitting" | "done" | "error";
  run: RunExerciseResponse | null;
  runMode: ExerciseRunMode | null;
  runState: AsyncActionState;
  runIsStale: boolean;
  readOnly?: boolean;
  onCodeChange: (value: string) => void;
  onBlankChange: (blankKey: string, value: string) => void;
  onExplanationChange: (value: string) => void;
  onPatchAnswerChange: Dispatch<SetStateAction<ReviewAiPatchAnswer>>;
  onRunPreview: () => void;
  onRunVisibleTests: () => void;
  onRetryRun: () => void;
  onSubmit: () => void;
};

function ReviewArchivedExerciseCard({
  title,
  result,
}: {
  title: string;
  result: ReviewExerciseResultResponse | null;
}) {
  const resultText = result
    ? `${completionResultLabel(result.result)} · ${formatScore(result.score)}`
    : "已离开当前编辑状态";
  return (
    <article className="review-tool-exercise review-archived-exercise-card" aria-label="已记录的复习题">
      <header className="review-archived-header">
        <span className="wb-kicker">复习练习</span>
        <span className="wb-state wb-state-submitted">已记录</span>
      </header>
      <h3>{title}</h3>
      <p>{result?.feedback ?? "这道题已经留在上方记录里，继续完成下面的新题。"}</p>
      <div className="review-archived-result">{resultText}</div>
    </article>
  );
}

function ReviewExerciseWorkbench({
  review,
  result,
  editorCode,
  filledBlanks,
  explanation,
  patchAnswer,
  submitDisabled,
  submitNotice,
  submitState,
  run,
  runMode,
  runState,
  runIsStale,
  readOnly = false,
  onCodeChange,
  onBlankChange,
  onExplanationChange,
  onPatchAnswerChange,
  onRunPreview,
  onRunVisibleTests,
  onRetryRun,
  onSubmit,
}: ReviewExerciseWorkbenchProps) {
  const exercise = review.review_exercise;
  const isPatchReview = exercise.exercise_type === "review_ai_patch";
  const stateClassName = reviewWorkbenchStateClassName(submitState);
  const runInFlight = runState.status === "loading";
  const editorLocked = readOnly || submitState === "submitting" || submitState === "done" || runInFlight;
  const runDisabled = readOnly || isPatchReview || submitState === "submitting" || submitState === "done" || runInFlight;
  const effectiveSubmitDisabled = readOnly || submitDisabled;

  return (
    <section className="exercise-workbench review-exercise-workbench" aria-label="复习变体练习">
      <div className="wb-header">
        <div className="wb-header-left">
          <span className="wb-kicker">复习练习</span>
          <h2 className="wb-title">{exercise.title}</h2>
        </div>
        <div className="wb-header-right">
          <span className="wb-meta-pill">{exercise.exercise_type}</span>
          <span className="wb-meta-pill">{runtimeLabel(exercise.runtime_profile.runtime_tier)}</span>
          <span className={stateClassName}>{reviewSubmitStateLabel(submitState)}</span>
        </div>
      </div>

      <div className="wb-context-bar">
        <span>{review.knowledge_point.title}</span>
        <span className="wb-context-sep" />
        <span>{reviewStageLabel(review.review_stage)}</span>
        <span className="wb-context-sep" />
        <span>已复习 {review.ReviewState.review_count} 次</span>
      </div>

      <div className="wb-split">
        <div className="wb-editor-pane">
          <div className="wb-prompt">
            <strong>{review.variant_reason}</strong>
            <p>{exercise.prompt_markdown}</p>
          </div>

          {!isPatchReview && exercise.code_blanks.length > 0 && (
            <div className="wb-blanks">
              {exercise.code_blanks.map((blank) => (
                <label className="wb-blank" key={blank.id}>
                  <span className="wb-blank-key">{blank.blank_key}</span>
                  <input
                    className="wb-blank-input"
                    value={filledBlanks[blank.blank_key] ?? ""}
                    placeholder={blank.placeholder}
                    disabled={editorLocked}
                    onChange={(event) => onBlankChange(blank.blank_key, event.target.value)}
                  />
                </label>
              ))}
            </div>
          )}

          {isPatchReview ? (
            <ReviewAiPatchEvidence exercise={exercise} />
          ) : (
            <div className="wb-editor-frame">
              <div className="wb-editor-toolbar">
                <div className="wb-editor-toolbar-left">
                  <span className="wb-editor-lang">{exercise.runtime_profile.language}</span>
                </div>
                <div className="wb-editor-toolbar-right">
                  <button className="wb-toolbar-btn" type="button" disabled={runDisabled} onClick={onRunPreview}>
                    运行预览
                  </button>
                  <button className="wb-toolbar-btn" type="button" disabled={runDisabled} onClick={onRunVisibleTests}>
                    运行可见测试
                  </button>
                  <button className="wb-toolbar-btn wb-toolbar-btn-primary" type="button" disabled={effectiveSubmitDisabled} onClick={onSubmit}>
                    {reviewSubmitButtonLabel(submitState)}
                  </button>
                </div>
              </div>
              <CodeEditor
                language={exercise.runtime_profile.language}
                value={editorCode}
                onChange={onCodeChange}
                readOnly={editorLocked}
                height="360px"
                dark
              />
            </div>
          )}

          <div className="wb-assist">
            <div className="wb-assist-tabs">
              <button className="wb-assist-tab active" type="button">
                {isPatchReview ? "审查结论" : "解释"}
              </button>
            </div>
            <div className="wb-assist-body">
              {isPatchReview ? (
                <ReviewAiPatchFields
                  answer={patchAnswer}
                  setAnswer={onPatchAnswerChange}
                  submitDisabled={effectiveSubmitDisabled}
                  submitState={submitState}
                  onSubmit={onSubmit}
                />
              ) : (
                <div className="wb-assist-panel">
                  <textarea
                    className="wb-explanation-input"
                    value={explanation}
                    placeholder="用自己的话说明为什么这样补全，后端会据此生成评分结果。"
                    disabled={submitState === "submitting" || submitState === "done"}
                    onChange={(event) => onExplanationChange(event.target.value)}
                  />
                  <div className="wb-assist-controls">
                    <span className="wb-round-badge">提交后才会更新复习节奏</span>
                    <button className="wb-toolbar-btn wb-toolbar-btn-primary" type="button" disabled={effectiveSubmitDisabled} onClick={onSubmit}>
                      {reviewSubmitButtonLabel(submitState)}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
          {effectiveSubmitDisabled && submitState !== "done" && submitNotice && <div className="wb-notice">{submitNotice}</div>}
        </div>

        {isPatchReview ? (
          <ReviewResultOutput result={result} submitState={submitState} />
        ) : (
          <ReviewExerciseOutput
            run={run}
            runMode={runMode}
            runState={runState}
            runIsStale={runIsStale}
            result={result}
            submitState={submitState}
            onRetryRun={onRetryRun}
          />
        )}
      </div>
    </section>
  );
}

function ReviewAiPatchEvidence({ exercise }: { exercise: ReviewSessionResponse["review_exercise"] }) {
  const metadata = exercise.metadata_json;
  const requirement = stringMeta(metadata, "requirement", exercise.prompt_markdown);
  const originalCode = stringMeta(metadata, "original_code", exercise.starter_code);
  const aiDiff = stringMeta(metadata, "ai_diff", "");
  const reviewFocus = stringMeta(metadata, "review_focus", "判断 AI 改动是否满足当前知识点要求。");

  return (
    <div className="patch-evidence review-patch-evidence">
      <h3>需求</h3>
      <p>{requirement}</p>
      <h3>原始代码</h3>
      <pre>{originalCode}</pre>
      <h3>AI 改动</h3>
      <pre>{aiDiff}</pre>
      <h3>审查焦点</h3>
      <p>{reviewFocus}</p>
    </div>
  );
}

function ReviewAiPatchFields({
  answer,
  setAnswer,
  submitDisabled,
  submitState,
  onSubmit,
}: {
  answer: ReviewAiPatchAnswer;
  setAnswer: Dispatch<SetStateAction<ReviewAiPatchAnswer>>;
  submitDisabled: boolean;
  submitState: "idle" | "submitting" | "done" | "error";
  onSubmit: () => void;
}) {
  return (
    <div className="wb-assist-panel">
      <label className="review-field">
        <span>结论</span>
        <select
          className="wb-select"
          value={answer.verdict}
          disabled={submitState === "submitting" || submitState === "done"}
          onChange={(event) =>
            setAnswer((current) => ({
              ...current,
              verdict: event.target.value as ReviewAiPatchAnswer["verdict"],
            }))
          }
        >
          <option value="fail">不通过</option>
          <option value="pass">通过</option>
          <option value="uncertain">不确定</option>
        </select>
      </label>
      <label className="review-field">
        <span>证据</span>
        <textarea
          className="wb-explanation-input"
          value={answer.evidence}
          placeholder="引用需求、diff 或测试信号。不能只写 tests passed。"
          disabled={submitState === "submitting" || submitState === "done"}
          onChange={(event) => setAnswer((current) => ({ ...current, evidence: event.target.value }))}
        />
      </label>
      <label className="review-field">
        <span>当前知识点风险</span>
        <textarea
          className="wb-explanation-input"
          value={answer.knowledge_point_risk}
          placeholder="说明这个改动会怎样影响当前知识点。"
          disabled={submitState === "submitting" || submitState === "done"}
          onChange={(event) => setAnswer((current) => ({ ...current, knowledge_point_risk: event.target.value }))}
        />
      </label>
      <div className="wb-assist-controls">
        <label className="review-field compact">
          <span>下一步</span>
          <select
            className="wb-select"
            value={answer.next_action}
            disabled={submitState === "submitting" || submitState === "done"}
            onChange={(event) =>
              setAnswer((current) => ({
                ...current,
                next_action: event.target.value as ReviewAiPatchAnswer["next_action"],
              }))
            }
          >
            <option value="request_change">要求修改</option>
            <option value="reject">拒绝改动</option>
            <option value="run_more_tests">补跑测试</option>
            <option value="accept">接受改动</option>
          </select>
        </label>
        <button className="wb-toolbar-btn wb-toolbar-btn-primary" type="button" disabled={submitDisabled} onClick={onSubmit}>
          {reviewSubmitButtonLabel(submitState)}
        </button>
      </div>
    </div>
  );
}

function ReviewExerciseOutput({
  run,
  runMode,
  runState,
  runIsStale,
  result,
  submitState,
  onRetryRun,
}: {
  run: RunExerciseResponse | null;
  runMode: ExerciseRunMode | null;
  runState: AsyncActionState;
  runIsStale: boolean;
  result: ReviewExerciseResultResponse | null;
  submitState: "idle" | "submitting" | "done" | "error";
  onRetryRun: () => void;
}) {
  const actionError = runState.status === "error" ? runState : null;
  const runLoading = runState.status === "loading";
  const hasFailedRun = run !== null && (run.runtime_status !== "success" || run.test_results.some((item) => !item.passed));
  const statusLabel = result
    ? reviewResultStatusLabel(result)
    : submitState === "submitting"
      ? "提交中"
      : submitState === "error"
        ? "提交失败"
        : runLoading
          ? "运行中"
          : actionError
            ? "运行失败"
            : runIsStale && run
              ? "需重跑"
              : run
                ? runtimeStatusLabel(run.runtime_status)
                : "待运行";
  const statusClassName = result
    ? reviewResultStatusClassName(result)
    : submitState === "error" || actionError || hasFailedRun
      ? "error"
      : run && !runIsStale
        ? "success"
        : "";

  return (
    <div className="wb-output-pane">
      <div className="wb-output-header">
        <span className="wb-output-title">运行与反馈</span>
        <span className={["wb-output-status", statusClassName].filter(Boolean).join(" ")}>{statusLabel}</span>
      </div>
      <div className="wb-output-body">
        {runLoading && (
          <div className="wb-output-loading">
            <div className="wb-spinner" />
            {runState.label}
          </div>
        )}
        {actionError && (
          <div className="wb-output-error">
            <span>{actionError.code}: {actionError.message}</span>
            {actionError.recoverable && (
              <button className="wb-toolbar-btn" type="button" onClick={onRetryRun}>
                重试
              </button>
            )}
          </div>
        )}
        {runIsStale && run && <div className="wb-output-stale">代码或空格已修改，旧运行结果仅供参考；请重新运行可见测试后再提交。</div>}
        {!run && !result && !runLoading && !actionError && submitState !== "submitting" && submitState !== "error" && (
          <div className="wb-output-empty">
            <div className="wb-output-empty-icon">▶</div>
            <p>先运行预览或可见测试。提交前必须有最新的可见测试结果。</p>
          </div>
        )}
        {run && <RuntimeFeedback result={run} runMode={runMode} />}
        {submitState === "submitting" && (
          <div className="wb-output-loading">
            <div className="wb-spinner" />
            正在提交复习结果……
          </div>
        )}
        {submitState === "error" && (
          <div className="wb-output-error">
            <span>提交失败，请检查输入后重试。</span>
          </div>
        )}
        {result && <ReviewResultDetails result={result} />}
      </div>
    </div>
  );
}

function ReviewResultOutput({
  result,
  submitState,
}: {
  result: ReviewExerciseResultResponse | null;
  submitState: "idle" | "submitting" | "done" | "error";
}) {
  const statusLabel = result
    ? reviewResultStatusLabel(result)
    : submitState === "error"
      ? "提交失败"
      : "待提交";
  const statusClassName = result ? reviewResultStatusClassName(result) : "";

  return (
    <div className="wb-output-pane">
      <div className="wb-output-header">
        <span className="wb-output-title">复习反馈</span>
        <span className={["wb-output-status", statusClassName].filter(Boolean).join(" ")}>{statusLabel}</span>
      </div>
      <div className="wb-output-body">
        {submitState === "submitting" && (
          <div className="wb-output-loading">
            <div className="wb-spinner" />
            正在提交复习结果……
          </div>
        )}
        {submitState === "error" && (
          <div className="wb-output-error">
            <span>提交失败，请检查输入后重试。</span>
          </div>
        )}
        {!result && submitState !== "submitting" && submitState !== "error" && (
          <div className="wb-output-empty">
            <div className="wb-output-empty-icon">↵</div>
            <p>完成左侧练习并提交后，这里会显示本题反馈；完成整个复习批次后才会显示下次复习安排。</p>
          </div>
        )}
        {result && <ReviewResultDetails result={result} />}
      </div>
    </div>
  );
}

function ReviewResultDetails({ result }: { result: ReviewExerciseResultResponse }) {
  const finalResult = isFinalReviewResult(result) ? result : null;
  return (
    <div className="review-result-stack">
      <p>{result.feedback}</p>
      {result.next_action === "next_exercise" && (
        <div className="wb-output-transition">
          本题已记录到当前复习批次，下一道题已经准备好。完成全部题目后，后端才会更新下次复习安排。
        </div>
      )}
      {result.next_action === "retry_same" && (
        <div className="wb-output-transition error">
          {result.clarification_question ?? "请补充解释后重新提交本题。"}
        </div>
      )}
      <div className="review-result-metrics">
        <div className="review-result-metric">
          <span>结果</span>
          <strong>{completionResultLabel(result.result)}</strong>
        </div>
        <div className="review-result-metric">
          <span>分数</span>
          <strong>{formatScore(result.score)}</strong>
        </div>
        {finalResult && (
          <>
            <div className="review-result-metric">
              <span>最终掌握</span>
              <strong>{fsrsRatingLabel(finalResult.fsrs_rating)}</strong>
            </div>
            <div className="review-result-metric">
              <span>下次复习</span>
              <strong>{formatDateTime(finalResult.due_at)}</strong>
            </div>
            <div className="review-result-metric">
              <span>遗忘风险</span>
              <strong>{riskLabel(finalResult.forget_risk)}</strong>
            </div>
          </>
        )}
      </div>
      {!finalResult && result.current_node?.type === "exercise" && (
        <div className="review-result-progress">
          当前批次进度：{result.current_node.completed_count}/{result.current_node.target_count}
        </div>
      )}
      {result.weak_points.length > 0 && (
        <div className="review-result-weak-points">
          <span>需要回看</span>
          {result.weak_points.map((point) => (
            <em key={point}>{point}</em>
          ))}
        </div>
      )}
    </div>
  );
}

function defaultFilledBlanks(review: ReviewSessionResponse): Record<string, string> {
  return defaultFilledBlanksForExercise(review.review_exercise);
}

function defaultFilledBlanksForExercise(exercise: ReviewSessionResponse["review_exercise"]): Record<string, string> {
  return Object.fromEntries(exercise.code_blanks.map((blank) => [blank.blank_key, blank.placeholder]));
}

function defaultReviewPatchAnswer(): ReviewAiPatchAnswer {
  return {
    verdict: "fail",
    evidence: "",
    knowledge_point_risk: "",
    next_action: "request_change",
  };
}

function prepareReviewConversationMessages(
  review: ReviewSessionResponse,
  restoredMessages: ConversationMessage[],
): PreparedReviewConversation {
  const messages = [...restoredMessages];
  const reviewCardResults: Record<string, ReviewCompletedExerciseCardState | null> = {};

  for (const entry of completedReviewExerciseEntries(review)) {
    const existing = messages.find((message) => isReviewExerciseCardMessageForExercise(message, review.session_id, entry.exerciseId));
    const cardMessage =
      existing ??
      createReviewExerciseCardMessage(review, {
        exerciseId: entry.exerciseId,
        title: entry.title,
      });
    if (!existing) {
      messages.push(cardMessage);
    }
    reviewCardResults[cardMessage.id] = entry.cardState;
  }

  if (!shouldShowReviewExerciseCard(review)) {
    return { messages, activeExerciseCardId: null, reviewCardResults };
  }
  const existing = messages.find((message) => isReviewExerciseCardMessage(message, review));
  if (existing) {
    reviewCardResults[existing.id] ??= null;
    return { messages, activeExerciseCardId: existing.id, reviewCardResults };
  }
  const cardMessage = createReviewExerciseCardMessage(review);
  messages.push(cardMessage);
  reviewCardResults[cardMessage.id] = null;
  return { messages, activeExerciseCardId: cardMessage.id, reviewCardResults };
}

function createReviewExerciseCardMessage(
  review: ReviewSessionResponse,
  override?: { exerciseId: string; title: string },
): ConversationMessage {
  const base = createMessage("agent", "", "Agent");
  const exerciseId = override?.exerciseId ?? review.review_exercise.id;
  const title = override?.title ?? review.review_exercise.title;
  return {
    ...base,
    id: reviewExerciseCardMessageId(review.session_id, exerciseId),
    status: "done",
    presentation: "attachment",
    attachment: {
      type: "review_exercise",
      sessionId: review.session_id,
      exerciseId,
      knowledgePointId: review.knowledge_point.id,
      title,
    },
  };
}

function reviewExerciseCardMessageId(sessionId: string, exerciseId: string): string {
  return `review-exercise-card-${sessionId}-${exerciseId}`;
}

function shouldShowReviewExerciseCard(review: ReviewSessionResponse): boolean {
  return !isReviewWarmupPending(review.review_stage) && review.current_node.type === "exercise";
}

function isReviewExerciseCardMessage(message: ConversationMessage, review: ReviewSessionResponse): boolean {
  return isReviewExerciseCardMessageForExercise(message, review.session_id, review.review_exercise.id);
}

function isReviewExerciseCardMessageForExercise(
  message: ConversationMessage,
  sessionId: string,
  exerciseId: string,
): boolean {
  return (
    message.attachment?.type === "review_exercise" &&
    message.attachment.sessionId === sessionId &&
    message.attachment.exerciseId === exerciseId
  );
}

function completedReviewExerciseEntries(review: ReviewSessionResponse): Array<{
  exerciseId: string;
  title: string;
  cardState: ReviewCompletedExerciseCardState | null;
}> {
  const stageState = review.review_stage_state as Record<string, unknown>;
  const plan = stageState.exercise_plan;
  if (!Array.isArray(plan)) {
    return [];
  }
  return plan.flatMap((item, index) => {
    if (!isRecord(item) || item.status !== "completed") {
      return [];
    }
    const exerciseId = stringValue(item.exercise_id);
    if (!exerciseId || exerciseId === review.review_exercise.id) {
      return [];
    }
    const title =
      stringValue(isRecord(item.exercise) ? item.exercise.title : null) ||
      stringValue(item.exercise_title) ||
      stringValue(item.title) ||
      `${review.knowledge_point.title}: 已完成复习题 ${index + 1}`;
    return [
      {
        exerciseId,
        title,
        cardState: completedCardStateFromPlanEntry(item, review),
      },
    ];
  });
}

function completedCardStateFromCurrentReview(
  review: ReviewSessionResponse,
  result: ReviewExerciseResultResponse,
  snapshot: {
    editorCode: string;
    filledBlanks: Record<string, string>;
    explanation: string;
    patchAnswer: ReviewAiPatchAnswer;
  },
): ReviewCompletedExerciseCardState {
  return {
    exercise: review.review_exercise,
    result,
    editorCode: snapshot.editorCode,
    filledBlanks: { ...snapshot.filledBlanks },
    explanation: snapshot.explanation,
    patchAnswer: { ...snapshot.patchAnswer },
    variantReason: review.variant_reason,
  };
}

function completedCardStateFromPlanEntry(
  entry: Record<string, unknown>,
  review: ReviewSessionResponse,
): ReviewCompletedExerciseCardState | null {
  const result = reviewResultFromPlanEntry(entry);
  const exercise = learningExerciseFromPlanEntry(entry);
  if (!result && !exercise) {
    return null;
  }
  return {
    exercise,
    result,
    editorCode: stringValue(entry.submitted_code) || exercise?.starter_code || "",
    filledBlanks: recordOfStrings(entry.filled_blanks) ?? (exercise ? defaultFilledBlanksForExercise(exercise) : {}),
    explanation: stringValue(entry.explanation),
    patchAnswer: reviewAiPatchAnswerFromPlanEntry(entry) ?? defaultReviewPatchAnswer(),
    variantReason:
      stringValue(entry.variant_reason) ||
      stringValue(entry.selection_reason) ||
      stringValue(isRecord(entry.variant) ? entry.variant.selection_reason : null) ||
      review.variant_reason,
  };
}

function reviewForCompletedCard(
  baseReview: ReviewSessionResponse,
  completedCard: ReviewCompletedExerciseCardState,
  exercise: LearningExercise,
): ReviewSessionResponse {
  const currentNode = baseReview.current_node;
  const targetCount = "target_count" in currentNode ? currentNode.target_count : 1;
  const completedCount = "completed_count" in currentNode ? currentNode.completed_count : targetCount;
  return {
    ...baseReview,
    review_exercise: exercise,
    review_stage: "exercise_feedback",
    current_node: {
      type: "exercise",
      stage: "exercise",
      can_pause: false,
      exercise,
      position: completedCount,
      target_count: targetCount,
      completed_count: completedCount,
      candidate_id: "",
    },
    variant_reason: completedCard.variantReason,
  };
}

function reviewResultFromPlanEntry(entry: Record<string, unknown>): ReviewExerciseResultResponse | null {
  const codeCompletionResult = codeCompletionResultFromPlanEntry(entry);
  if (!codeCompletionResult) {
    return null;
  }
  return {
    result: codeCompletionResult.result,
    score: codeCompletionResult.score,
    score_breakdown: codeCompletionResult.score_breakdown,
    hard_gates: codeCompletionResult.hard_gates,
    test_pass_rate: codeCompletionResult.test_pass_rate,
    hint_usage_count: codeCompletionResult.hint_usage_count,
    error_count: codeCompletionResult.error_count,
    fsrs_rating: codeCompletionResult.fsrs_rating,
    weak_points: codeCompletionResult.weak_points,
    error_cause: codeCompletionResult.error_cause,
    feedback: codeCompletionResult.feedback,
    code_completion_result: codeCompletionResult,
    attempt_id: stringValue(entry.attempt_id) || undefined,
    next_action: "next_exercise",
  };
}

function codeCompletionResultFromPlanEntry(entry: Record<string, unknown>): CodeCompletionResult | null {
  const completion = isRecord(entry.code_completion_result) ? entry.code_completion_result : {};
  const result = completionResultValue(entry.result) ?? completionResultValue(completion.result);
  const score = numberValue(entry.score) ?? numberValue(completion.score);
  if (!result || score === null) {
    return null;
  }
  return {
    result,
    score,
    score_breakdown: recordOfNumbers(entry.score_breakdown) ?? recordOfNumbers(completion.score_breakdown) ?? {},
    hard_gates: hardGatesValue(completion.hard_gates),
    test_pass_rate: numberValue(entry.test_pass_rate) ?? numberValue(completion.test_pass_rate) ?? 0,
    hint_usage_count: numberValue(entry.hint_usage_count) ?? numberValue(completion.hint_usage_count) ?? 0,
    error_count: numberValue(entry.error_count) ?? numberValue(completion.error_count) ?? 0,
    weak_points: stringListValue(entry.weak_points).length > 0 ? stringListValue(entry.weak_points) : stringListValue(completion.weak_points),
    error_cause: stringOrNull(entry.error_cause) ?? stringOrNull(completion.error_cause),
    feedback:
      stringValue(entry.feedback) ||
      stringValue(completion.feedback) ||
      "本题已记录到当前复习批次，继续完成下面的新题。",
    next_action: nextActionValue(completion.next_action) ?? "schedule_review",
    fsrs_rating: fsrsRatingValue(entry.fsrs_rating) ?? fsrsRatingValue(completion.fsrs_rating) ?? "Good",
    ...(isRecord(completion.review_ai_patch_result) ? { review_ai_patch_result: completion.review_ai_patch_result as CodeCompletionResult["review_ai_patch_result"] } : {}),
  };
}

function learningExerciseFromPlanEntry(entry: Record<string, unknown>): LearningExercise | null {
  const exercise = isRecord(entry.exercise) ? entry.exercise : null;
  if (!exercise) {
    return null;
  }
  if (
    typeof exercise.id !== "string" ||
    typeof exercise.knowledge_point_id !== "string" ||
    typeof exercise.runtime_profile_id !== "string" ||
    typeof exercise.title !== "string" ||
    typeof exercise.exercise_type !== "string" ||
    typeof exercise.prompt_markdown !== "string" ||
    typeof exercise.starter_code !== "string" ||
    typeof exercise.visible_test_policy !== "string" ||
    typeof exercise.requires_explanation !== "boolean" ||
    typeof exercise.runtime_profile !== "object" ||
    exercise.runtime_profile === null ||
    !Array.isArray(exercise.code_blanks) ||
    !Array.isArray(exercise.test_cases)
  ) {
    return null;
  }
  return exercise as LearningExercise;
}

function reviewAiPatchAnswerFromPlanEntry(entry: Record<string, unknown>): ReviewAiPatchAnswer | null {
  const fromEntry = reviewAiPatchAnswerValue(entry.review_ai_patch_answer);
  if (fromEntry) {
    return fromEntry;
  }
  const submitted = stringValue(entry.submitted_code);
  if (!submitted.startsWith("{")) {
    return null;
  }
  try {
    return reviewAiPatchAnswerValue(JSON.parse(submitted));
  } catch {
    return null;
  }
}

function reviewAiPatchAnswerValue(value: unknown): ReviewAiPatchAnswer | null {
  if (!isRecord(value)) {
    return null;
  }
  const verdict = value.verdict === "pass" || value.verdict === "fail" || value.verdict === "uncertain" ? value.verdict : null;
  const nextAction =
    value.next_action === "accept" ||
    value.next_action === "reject" ||
    value.next_action === "request_change" ||
    value.next_action === "run_more_tests"
      ? value.next_action
      : null;
  if (!verdict || !nextAction) {
    return null;
  }
  return {
    verdict,
    evidence: stringValue(value.evidence),
    knowledge_point_risk: stringValue(value.knowledge_point_risk),
    next_action: nextAction,
  };
}

function completionResultValue(value: unknown): ReviewExerciseResultResponse["result"] | null {
  if (value === "failed" || value === "partial" || value === "passed" || value === "easy") {
    return value;
  }
  return null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function fsrsRatingValue(value: unknown): CodeCompletionResult["fsrs_rating"] | null {
  if (value === "Again" || value === "Hard" || value === "Good" || value === "Easy") {
    return value;
  }
  return null;
}

function nextActionValue(value: unknown): CodeCompletionResult["next_action"] | null {
  if (
    value === "retry_same" ||
    value === "show_hint" ||
    value === "explain_error" ||
    value === "review_variant" ||
    value === "schedule_review" ||
    value === "advance_next"
  ) {
    return value;
  }
  return null;
}

function recordOfStrings(value: unknown): Record<string, string> | null {
  if (!isRecord(value)) {
    return null;
  }
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, typeof item === "string" ? item : String(item ?? "")]));
}

function recordOfNumbers(value: unknown): Record<string, number> | null {
  if (!isRecord(value)) {
    return null;
  }
  const entries = Object.entries(value).flatMap(([key, item]) => {
    const numeric = numberValue(item);
    return numeric === null ? [] : [[key, numeric] as const];
  });
  return Object.fromEntries(entries);
}

function hardGatesValue(value: unknown): CodeCompletionResult["hard_gates"] {
  const gates = isRecord(value) ? value : {};
  return {
    runtime_gate: gates.runtime_gate === true,
    test_gate: gates.test_gate === true,
    core_blank_gate: gates.core_blank_gate === true,
    explanation_gate: gates.explanation_gate === true,
  };
}

function stringListValue(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) => {
    const text = stringValue(item);
    return text ? [text] : [];
  });
}

function stringOrNull(value: unknown): string | null {
  const text = stringValue(value);
  return text || null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

async function restoreReviewConversationMessages(input: {
  userId: string;
  sessionId: string;
  fallbackReview: ReviewSessionResponse;
}): Promise<ConversationMessage[]> {
  try {
    const history = await fetchReviewMessages({
      userId: input.userId,
      sessionId: input.sessionId,
    });
    const restored = history.messages
      .filter((message) => !isLegacyReviewExerciseResultMessage(message))
      .map(reviewHistoryMessageToConversationMessage);
    if (restored.length > 0) {
      return restored;
    }
  } catch {
    // Fallback keeps the review usable if a legacy backend lacks the history endpoint.
  }
  return initialReviewConversationMessages(input.fallbackReview);
}

function isLegacyReviewExerciseResultMessage(message: ReviewHistoryMessage): boolean {
  return message.client_message_id?.includes(":exercise-result:") ?? false;
}

function reviewHistoryMessageToConversationMessage(message: ReviewHistoryMessage): ConversationMessage {
  return {
    id: `history-${message.id}`,
    speaker: message.role === "user" ? "user" : "agent",
    text: message.content,
    label: message.role === "agent" ? "Agent" : undefined,
    status: "done",
  };
}

function initialReviewConversationMessages(review: ReviewSessionResponse): ConversationMessage[] {
  const messages: ConversationMessage[] = [];
  if (isReviewWarmupPending(review.review_stage)) {
    messages.push(createMessage("agent", buildWarmupQuestionMessage(review), "Agent"));
  }
  return prepareReviewConversationMessages(review, messages).messages;
}

function patchOriginalCode(metadata: Record<string, unknown>): string {
  return stringMeta(metadata, "original_code", "");
}

function stringMeta(metadata: Record<string, unknown>, key: string, fallback: string): string {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value : fallback;
}

function isReviewWarmupPending(stage: ReviewSessionResponse["review_stage"]): boolean {
  return stage === "warmup" || stage === "warmup_repair";
}

function isWarmupSkipIntent(content: string): boolean {
  return /^(跳过|skip)$/i.test(content.trim());
}

function buildWarmupQuestionMessage(review: ReviewSessionResponse): string {
  return buildWarmupPromptText(review.review_stage, review.warmup.question);
}

function buildWarmupResultMessage(result: ReviewWarmupResultResponse): string {
  if (isReviewWarmupPending(result.review_stage)) {
    return result.warmup.feedback ?? buildWarmupPromptText(result.review_stage, result.warmup.question);
  }
  const lines = [result.warmup.feedback ?? `热身结果：${warmupResultLabel(result.warmup.result)}。`];
  lines.push("下面直接进一道同知识点的题，看看你能不能在代码里认出来。");
  return lines.join("\n\n");
}

function buildWarmupPromptText(stage: ReviewSessionResponse["review_stage"], question: string): string {
  const prompt = question.trim() || "这类代码最容易让人误判的地方是什么？";
  if (stage === "warmup_repair") {
    return `我还没确认这个点已经稳住。换个更具体的说法：\n${prompt}\n\n不用写完整答案，说出你会警惕什么就行；想跳过就输入“跳过”。`;
  }
  return `先把这个点唤醒一下：\n${prompt}\n\n不用写完整答案，说一句你记得的风险点就行；想跳过就输入“跳过”。`;
}

function reviewStageLabel(stage: ReviewSessionResponse["review_stage"]): string {
  if (stage === "warmup") {
    return "热身";
  }
  if (stage === "warmup_repair") {
    return "再想一下";
  }
  if (stage === "submitted" || stage === "final_summary") {
    return "已完成";
  }
  return "变体练习";
}

function warmupResultLabel(result: ReviewSessionResponse["warmup"]["result"]): string {
  if (result === "correct") {
    return "已唤醒";
  }
  if (result === "skipped") {
    return "已跳过";
  }
  if (result === "unclear") {
    return "不明确";
  }
  if (result === "incorrect") {
    return "需修正";
  }
  return "待完成";
}

function buildSubmittedCode(code: string, filledBlanks: Record<string, string>): string {
  return Object.entries(filledBlanks).reduce((current, [blankKey, value]) => {
    const token = `__${blankKey.toUpperCase()}__`;
    return current.replaceAll(token, value);
  }, code);
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "未安排";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function riskLabel(value: ReviewDueItem["forget_risk"]): string {
  if (value === "low") {
    return "低";
  }
  if (value === "high") {
    return "高";
  }
  return "正常";
}

function isFinalReviewResult(
  result: ReviewExerciseResultResponse,
): result is ReviewExerciseResultResponse & {
  due_at: string | null;
  forget_risk: ReviewDueItem["forget_risk"];
  ReviewState: NonNullable<ReviewExerciseResultResponse["ReviewState"]>;
  KnowledgePoint: NonNullable<ReviewExerciseResultResponse["KnowledgePoint"]>;
} {
  return (
    result.next_action === "schedule_review" &&
    "due_at" in result &&
    result.forget_risk !== undefined &&
    result.ReviewState !== undefined &&
    result.KnowledgePoint !== undefined
  );
}

function reviewResultStatusLabel(result: ReviewExerciseResultResponse): string {
  if (isFinalReviewResult(result)) {
    return completionResultLabel(result.result);
  }
  if (result.next_action === "retry_same") {
    return "需要补充";
  }
  return "本题已提交";
}

function reviewResultStatusClassName(result: ReviewExerciseResultResponse): string {
  return result.next_action === "retry_same" || result.result === "failed" ? "error" : "success";
}

function reviewWorkbenchStateClassName(submitState: "idle" | "submitting" | "done" | "error"): string {
  if (submitState === "submitting") {
    return "wb-state wb-state-running";
  }
  if (submitState === "done") {
    return "wb-state wb-state-submitted";
  }
  if (submitState === "error") {
    return "wb-state wb-state-dirty";
  }
  return "wb-state";
}

function reviewSubmitStateLabel(submitState: "idle" | "submitting" | "done" | "error"): string {
  if (submitState === "submitting") {
    return "提交中";
  }
  if (submitState === "done") {
    return "已提交";
  }
  if (submitState === "error") {
    return "提交失败";
  }
  return "待提交";
}

function reviewSubmitButtonLabel(submitState: "idle" | "submitting" | "done" | "error"): string {
  if (submitState === "submitting") {
    return "提交中...";
  }
  if (submitState === "done") {
    return "已提交";
  }
  return "提交复习结果";
}

function reviewSubmitNotice(
  exercise: ReviewSessionResponse["review_exercise"],
  submitState: "idle" | "submitting" | "done" | "error",
  state: {
    blankValuesComplete: boolean;
    explanationRequired: boolean;
    explanationComplete: boolean;
    patchAnswerComplete: boolean;
    runRequired: boolean;
    hasRun: boolean;
    runMode: ExerciseRunMode | null;
    runIsStale: boolean;
    runStatus: RunExerciseResponse["runtime_status"] | null;
    runInFlight: boolean;
  },
): string {
  if (submitState === "submitting") {
    return "当前提交正在处理中，请等待后端返回结果。";
  }
  if (exercise.exercise_type === "review_ai_patch") {
    return state.patchAnswerComplete ? "提交后先记录到本次复习批次，最终结果由后端统一结算。" : "证据和风险说明都填写后才能提交审查结论。";
  }
  if (!state.blankValuesComplete) {
    return "请先补全所有空格，再提交复习结果。";
  }
  if (state.explanationRequired && !state.explanationComplete) {
    return "请先用自己的话解释为什么这样补全，这道题需要解释后才能提交。";
  }
  if (state.runInFlight) {
    return "当前运行正在处理中，请等待右侧返回结果。";
  }
  if (state.runRequired && !state.hasRun) {
    return "先运行可见测试，让右侧显示真实运行结果后再提交。";
  }
  if (state.runRequired && state.runMode === "preview") {
    return "预览只用于观察效果；提交前还需要运行一次可见测试。";
  }
  if (state.runRequired && state.runIsStale) {
    return "代码或空格已经改过，请重新运行可见测试后再提交。";
  }
  if (state.runRequired && state.runStatus && state.runStatus !== "success") {
    return `这次运行状态是${runtimeStatusLabel(state.runStatus)}，请修正后重新运行可见测试。`;
  }
  return "提交后先记录本题结果；完成整个复习批次后，后端才会更新下次复习安排。";
}

function formatScore(score: number): string {
  return Number.isInteger(score) ? String(score) : score.toFixed(2);
}

function createClientId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `${prefix}_${uuid}` : `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}
