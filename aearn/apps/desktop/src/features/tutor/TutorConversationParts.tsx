import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";

import { useGraphemeTypewriter } from "../../hooks/useGraphemeTypewriter";
import type {
  ExerciseAttemptOutcome, TeachingSessionGroupProjection, TutorContextReference,
  TutorContextReferenceDraft, TutorHistoryItem, TutorHistoryMessage, TutorInteractionRequestItem,
  TutorPublicArtifactItem, TutorPublicBranchGroup, TutorPublicTurn, TutorQueuedInput, TutorRuntimeOutput,
} from "../../types";
import {
  Button, DisclosureRow, IconChevronDown, IconChevronUp, IconDelete, IconEdit, IconQueue,
  IconSend, IconStop, Input, StateDot,
} from "../../ui/dsh-derived";
import { ClarificationBranchGroup, InlineArtifactMessage, SafeMarkdown, type TutorArtifactActionRequest } from "./artifacts";
import {
  displayQueuePauseReason, groupTimelineAroundArtifacts, requestDraftValid, runtimeReasoningText,
  TUTOR_TEXT_REVEAL_INTERVAL_MS, TUTOR_THINKING_AUTO_COLLAPSE_DELAY_MS,
  type RequestDraft, type TutorComposerReference, type TutorLiveRuntimeOutputState,
  type TutorRecentCompletion,
} from "./tutorConversationModel";

const GENERAL_EXAMPLES = ["帮我理清闭包和作用域", "我想系统复习 DOM 事件", "这个报错我不知道从哪里开始看"] as const;

export function Boundary({ eyebrow, title, children }: { eyebrow: string; title: string; children: string }) { return <section className="tutor-workspace tutor-workspace-boundary" aria-labelledby="tutor-workspace-title"><p className="tutor-panel-eyebrow">{eyebrow}</p><h1 id="tutor-workspace-title">{title}</h1><p>{children}</p></section>; }

export function Composer({ planning, compact, planningIdle, planningPlaceholder, selectedConversationId, text, status, disabled, sendLabel, contextReferences, composerRef, onTextChange, onKeyDown, onSubmit, onRemoveReference }: {
  planning: boolean; compact: boolean; planningIdle: boolean; planningPlaceholder?: string; selectedConversationId: string | null; text: string; status: "idle" | "submitting"; disabled: boolean; sendLabel: string;
  contextReferences: TutorComposerReference[]; composerRef: RefObject<HTMLTextAreaElement | null>;
  onTextChange: (value: string) => void; onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void; onSubmit: () => void; onRemoveReference?: (id: string) => void;
}) {
  const inputDisabled = disabled || status === "submitting";
  const placeholder = planning
    ? planningPlaceholder ?? "描述你想学习什么"
    : "例如：我会写基础 JavaScript，但总弄不清闭包里的变量什么时候会保留。";
  const form = <form className={`tutor-composer${compact ? " tutor-composer-chatgpt" : ""}`} onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
    <label className={compact ? "visually-hidden" : undefined} htmlFor="tutor-composer-input">{planning ? "告诉 Tutor 你的目标或调整意见" : selectedConversationId ? "继续当前对话" : "从你的学习目标开始"}</label>
    {contextReferences.length > 0 ? <TutorReferenceDraftChips references={contextReferences} disabled={inputDisabled} onRemove={onRemoveReference} /> : null}
    {compact ? <div className="tutor-composer-chatgpt-shell">
      <textarea ref={composerRef} id="tutor-composer-input" value={text} rows={2} maxLength={16_000} placeholder={placeholder} disabled={inputDisabled} onChange={(event) => onTextChange(event.target.value)} onKeyDown={onKeyDown} />
      <button className="tutor-composer-send" type="submit" aria-label={sendLabel} title={sendLabel} disabled={inputDisabled || !text.trim()}><IconSend /></button>
    </div> : <>
      <textarea ref={composerRef} id="tutor-composer-input" value={text} rows={4} maxLength={16_000} placeholder={placeholder} disabled={inputDisabled} onChange={(event) => onTextChange(event.target.value)} onKeyDown={onKeyDown} />
      <div className="tutor-composer-footer"><div className="tutor-goal-examples" aria-label="目标示例">{GENERAL_EXAMPLES.map((example) => <button key={example} type="button" onClick={() => onTextChange(example)} disabled={inputDisabled}>{example}</button>)}</div><Button variant="primary" type="submit" busy={status === "submitting"} disabled={disabled || !text.trim()} icon={<IconSend />}>{sendLabel}</Button></div>
    </>}
    {!planningIdle && <p className="tutor-composer-hint">按 Ctrl / ⌘ + Enter 发送。运行中发送会排入 Queue，不会隐式打断当前 Turn。</p>}
  </form>;
  return compact ? <div className={`tutor-chatgpt-composer-area${planningIdle ? " idle" : ""}`}>{form}</div> : form;
}


export function TypedRequestSeat({ request, draft, busy, disabled, onDraftChange, onSubmit, onApprove }: {
  request: TutorInteractionRequestItem; draft: RequestDraft; busy: boolean; disabled: boolean;
  onDraftChange: (draft: RequestDraft) => void; onSubmit: () => void; onApprove: (decision: "approve" | "deny") => void;
}) {
  return <section className="tutor-request-seat" aria-labelledby={`request-${request.id}`}>
    <strong className="tutor-request-seat-heading" id={`request-${request.id}`}>{request.prompt}</strong>
    {request.actor === "authority" ? <p className="tutor-muted-copy">此请求等待受信 authority 结果，普通 composer 与 Queue 控制保持锁定。</p> : request.kind === "approval" ? <div className="tutor-approval-card"><p>{request.presentation.summary}</p><span>风险级别：{request.presentation.risk_level}</span><div className="tutor-inline-actions"><Button variant="primary" busy={busy} disabled={disabled || busy} onClick={() => onApprove("approve")}>批准</Button><Button variant="outline" disabled={disabled || busy} onClick={() => onApprove("deny")}>拒绝</Button></div></div> : <form onSubmit={(event) => { event.preventDefault(); onSubmit(); }} className="tutor-request-form">
      <RequestControl request={request} draft={draft} disabled={disabled || busy} onDraftChange={onDraftChange} />
      <Button variant="primary" type="submit" busy={busy} disabled={disabled || busy || !requestDraftValid(request, draft)}>提交响应</Button>
    </form>}
  </section>;
}

export function RequestControl({ request, draft, disabled, onDraftChange }: { request: Extract<TutorInteractionRequestItem, { kind: "elicitation" }>; draft: RequestDraft; disabled: boolean; onDraftChange: (draft: RequestDraft) => void }) {
  const presentation = request.presentation;
  if (presentation.type === "integer") return <Input className="tutor-request-input" type="number" min={presentation.minimum} max={presentation.maximum} step={presentation.step} value={typeof draft === "string" ? draft : ""} disabled={disabled} onChange={(event) => onDraftChange(event.target.value)} aria-label={request.prompt} />;
  if (presentation.type === "single_select") {
    const selected = typeof draft === "string" ? draft : "";
    return <fieldset className="tutor-request-options tutor-request-options-grid"><legend className="visually-hidden">{request.prompt}</legend>{presentation.options.map((option) => <label key={option.value}><input type="radio" name={`request-${request.id}`} value={option.value} checked={selected === option.value} disabled={disabled} onChange={() => onDraftChange(option.value)} /><span>{option.label}</span></label>)}</fieldset>;
  }
  if (presentation.type === "multi_select") {
    const selected = Array.isArray(draft) ? draft : [];
    return <fieldset className="tutor-request-options"><legend className="visually-hidden">{request.prompt}</legend>{presentation.options.map((option) => <label key={option.value}><input type="checkbox" checked={selected.includes(option.value)} disabled={disabled || (!selected.includes(option.value) && selected.length >= presentation.maximum_selections)} onChange={(event) => onDraftChange(event.target.checked ? [...selected, option.value] : selected.filter((value) => value !== option.value))} /><span>{option.label}</span></label>)}</fieldset>;
  }
  return <textarea className="tutor-request-textarea" rows={presentation.type === "text" && presentation.multiline ? 4 : 2} minLength={presentation.type === "text" ? presentation.minimum_length : undefined} maxLength={presentation.type === "text" ? presentation.maximum_length : undefined} value={typeof draft === "string" ? draft : ""} disabled={disabled} onChange={(event) => onDraftChange(event.target.value)} aria-label={request.prompt} />;
}

export function QueueTray({ items, maxPending, activeTurn, paused, pauseReason, disabled, busyKey, editingId, editDraft, onBeginEdit, onCancelEdit, onEditDraft, onSaveEdit, onMove, onDelete, onSteer, onExecute, onResume }: {
  items: TutorQueuedInput[]; maxPending: number; activeTurn: TutorPublicTurn | null; paused: boolean; pauseReason: string | null; disabled: boolean; busyKey: string | null; editingId: string | null; editDraft: string;
  onBeginEdit: (item: TutorQueuedInput) => void; onCancelEdit: () => void; onEditDraft: (value: string) => void; onSaveEdit: (item: TutorQueuedInput) => void; onMove: (id: string, direction: -1 | 1) => void; onDelete: (item: TutorQueuedInput) => void; onSteer: (item: TutorQueuedInput) => void; onExecute: (item: TutorQueuedInput) => void; onResume: () => void;
}) {
  return <section className="tutor-queue-tray" aria-label="待处理 Queue"><header><div><IconQueue /><strong>Queue</strong><span>{items.length}/{maxPending}</span></div>{paused && <Button size="sm" variant="outline" disabled={disabled} busy={busyKey === "resume"} onClick={onResume}>继续队列</Button>}</header>{paused && <p className="tutor-queue-pause">队列已暂停：{displayQueuePauseReason(pauseReason)}</p>}{activeTurn && <p className="tutor-queue-active-hint">Steer 会影响当前处理并共享本 Turn 预算；中断并执行会结束当前 Turn 并创建 fresh Turn。</p>}<ol>{items.map((item, index) => <li key={item.item_id}>
    {editingId === item.item_id ? <div className="tutor-queue-edit"><textarea value={editDraft} onChange={(event) => onEditDraft(event.target.value)} disabled={disabled} rows={2} autoFocus /><div><Button size="sm" variant="primary" busy={busyKey === `edit:${item.item_id}`} disabled={disabled || !editDraft.trim()} onClick={() => onSaveEdit(item)}>保存</Button><Button size="sm" onClick={onCancelEdit}>取消</Button></div></div> : <><p>{item.content}</p><div className="tutor-queue-actions"><Button variant="icon" aria-label="编辑 Queue 项" title="编辑" disabled={disabled} icon={<IconEdit />} onClick={() => onBeginEdit(item)} /><Button variant="icon" aria-label="上移 Queue 项" title="上移" disabled={disabled || index === 0} icon={<IconChevronUp />} onClick={() => onMove(item.item_id, -1)} /><Button variant="icon" aria-label="下移 Queue 项" title="下移" disabled={disabled || index === items.length - 1} icon={<IconChevronDown />} onClick={() => onMove(item.item_id, 1)} /><Button variant="icon" aria-label="删除 Queue 项" title="删除" disabled={disabled} busy={busyKey === `delete:${item.item_id}`} icon={<IconDelete />} onClick={() => onDelete(item)} />{activeTurn && <Button size="sm" variant="outline" disabled={disabled} busy={busyKey === `steer:${item.item_id}`} onClick={() => onSteer(item)}>Steer</Button>}<Button size="sm" variant="primary" disabled={disabled} busy={busyKey === `execute:${item.item_id}`} title={activeTurn ? "中断当前 Turn，并以该 Queue 项创建 fresh Turn" : "以该 Queue 项创建 fresh Turn"} onClick={() => onExecute(item)}>{activeTurn ? "中断并执行" : "立即执行"}</Button></div></>}
  </li>)}</ol></section>;
}

type GroupedTeachingTimeline = {
  current: TutorHistoryItem[];
  history: Array<{ session: TeachingSessionGroupProjection; items: TutorHistoryItem[] }>;
  legacy: TutorHistoryItem[];
};

export function groupTeachingTimeline(
  timeline: TutorHistoryItem[],
  groups: TeachingSessionGroupProjection[],
  activeSessionId: string | null,
  branches: TutorPublicBranchGroup[] = [],
): GroupedTeachingTimeline {
  if (groups.length === 0 || !activeSessionId) return { current: timeline, history: [], legacy: [] };
  const active = groups.find((group) => group.session_id === activeSessionId) ?? null;
  if (!active) return { current: timeline, history: [], legacy: [] };
  const sessionById = new Map(groups.map((group) => [group.session_id, group]));
  const turnOwnership = new Map<string, TeachingSessionGroupProjection>();
  for (const group of groups) for (const turnId of group.turn_ids) turnOwnership.set(turnId, group);
  const branchItemOwnership = new Map<string, TeachingSessionGroupProjection>();
  for (const branch of branches) {
    const group = sessionById.get(branch.teaching_session_id);
    if (!group) continue;
    for (const reference of branch.items) branchItemOwnership.set(`${reference.item_kind}:${reference.item_id}`, group);
  }
  const current: TutorHistoryItem[] = [];
  const legacy: TutorHistoryItem[] = [];
  const historical = new Map<string, TutorHistoryItem[]>();
  for (const item of timeline) {
    const group = item.kind === "artifact"
      ? sessionById.get(item.teaching_session_id) ?? null
      : branchItemOwnership.get(`${item.kind}:${item.id}`) ?? (historyItemTurnId(item) ? turnOwnership.get(historyItemTurnId(item)!) ?? null : null);
    if (group?.session_id === activeSessionId) current.push(item);
    else if (group) historical.set(group.session_id, [...(historical.get(group.session_id) ?? []), item]);
    else legacy.push(item);
  }
  return {
    current,
    history: groups.filter((group) => group.session_id !== activeSessionId).map((session) => ({ session, items: historical.get(session.session_id) ?? [] })),
    legacy,
  };
}

export function TeachingSessionTimeline({ groups, legacyItems, branches, conversationId, newArtifactIds, recentCompletion, writeEnabled, mutationBusy, onRetry, onReference, onArtifactAction, loadArtifactDetail }: {
  groups: GroupedTeachingTimeline["history"];
  legacyItems: TutorHistoryItem[];
  branches: TutorPublicBranchGroup[];
  conversationId: string;
  newArtifactIds: ReadonlySet<string>;
  recentCompletion: TutorRecentCompletion | null;
  writeEnabled: boolean;
  mutationBusy: string | null;
  onRetry: (turnId: string) => void;
  onReference?: (reference: TutorContextReferenceDraft, label: string) => void;
  onArtifactAction?: (request: TutorArtifactActionRequest) => void;
  loadArtifactDetail?: (artifact: TutorPublicArtifactItem) => Promise<TutorPublicArtifactItem>;
}) {
  if (groups.length === 0 && legacyItems.length === 0) return null;
  return <section className="teaching-session-history" aria-label="历史教学分段">
    {groups.map(({ session, items }) => <details key={session.session_id} className="teaching-session-group">
      <summary><span><strong>{session.knowledge_key}</strong><small>{displayTeachingSessionStatus(session.status)} · {displayTeachingMode(session.mode)}</small></span><time>{formatTeachingSessionTime(session.last_activity_at)}</time></summary>
      <div className="teaching-session-readonly" aria-label={`${session.knowledge_key} 历史分段，只读`}>
        <p>历史 teaching session · 只读。展开不会改变当前 Composer、mode 或下一步。</p>
        {items.length > 0 ? <TimelineSequence items={items} branches={branches} conversationId={conversationId} newArtifactIds={newArtifactIds} recentCompletion={recentCompletion} writeEnabled={false} mutationBusy={mutationBusy} onRetry={onRetry} loadArtifactDetail={loadArtifactDetail} /> : <span>当前 bounded snapshot 中没有该分段的消息；可使用“加载更早记录”继续读取。</span>}
        {items.map((item) => item.kind === "message" && item.turn_id && onReference ? <button
          key={`reference:${session.session_id}:${item.id}`}
          className="tutor-text-button teaching-session-reference-button"
          type="button"
          disabled={!writeEnabled}
          onClick={() => onReference({
            kind: "teaching_session_message",
            learning_track_id: session.track_id,
            knowledge_key: session.knowledge_key,
            teaching_session_id: session.session_id,
            message_id: item.id,
          }, `历史${item.role === "learner" ? "提问" : "讲解"} · ${session.knowledge_key}`)}
        >引用此消息</button> : null)}
      </div>
    </details>)}
    {legacyItems.length > 0 ? <details className="teaching-session-group legacy"><summary><span><strong>教学分段启用前的对话</strong><small>Track conversation history · 只读</small></span></summary><div className="teaching-session-readonly"><TimelineSequence items={legacyItems} branches={branches} conversationId={conversationId} newArtifactIds={newArtifactIds} recentCompletion={recentCompletion} writeEnabled={false} mutationBusy={mutationBusy} onRetry={onRetry} onArtifactAction={onArtifactAction} loadArtifactDetail={loadArtifactDetail} /></div></details> : null}
  </section>;
}

export function historyItemTurnId(item: TutorHistoryItem): string | null {
  if (item.kind === "process") return item.run_id;
  return item.turn_id;
}

export function displayTeachingSessionStatus(status: TeachingSessionGroupProjection["status"]): string {
  return { active: "进行中", paused: "已暂停", completed: "已完成", blocked: "authority 已变化" }[status];
}

export function displayTeachingMode(mode: TeachingSessionGroupProjection["mode"]): string {
  return mode === "guided" ? "Guided" : "自由阅读";
}

export function formatTeachingSessionTime(value: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "" : new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(parsed);
}

export function TimelineSequence({ items, branches, conversationId, newArtifactIds, recentCompletion, writeEnabled, mutationBusy, onRetry, onArtifactAction, loadArtifactDetail }: {
  items: TutorHistoryItem[];
  branches: TutorPublicBranchGroup[];
  conversationId: string;
  newArtifactIds: ReadonlySet<string>;
  recentCompletion: TutorRecentCompletion | null;
  writeEnabled: boolean;
  mutationBusy: string | null;
  onRetry: (turnId: string) => void;
  onArtifactAction?: (request: TutorArtifactActionRequest) => void;
  loadArtifactDetail?: (artifact: TutorPublicArtifactItem) => Promise<TutorPublicArtifactItem>;
}) {
  const nodes = groupTimelineAroundArtifacts(items, branches);
  return <>{nodes.map((node) => node.kind === "branch"
    ? <ClarificationBranchGroup key={`branch:${node.branch.branch_id}`} conversationId={conversationId} branch={node.branch}>
        {node.items.map((item) => <TimelineItem
          key={`branch-item:${node.branch.branch_id}:${item.kind}:${item.id}`}
          item={item}
          recentCompletion={recentCompletion}
          writeEnabled={writeEnabled}
          mutationBusy={mutationBusy}
          onRetry={onRetry}
        />)}
      </ClarificationBranchGroup>
    : <TimelineItem
        key={`${node.item.kind}:${node.item.id}`}
        item={node.item}
        recentCompletion={recentCompletion}
        writeEnabled={writeEnabled}
        mutationBusy={mutationBusy}
        onRetry={onRetry}
        artifactAutoReveal={node.item.kind === "artifact" && newArtifactIds.has(node.item.id)}
        artifactTerminalCollapseMarker={node.terminalCollapseMarker}
        onArtifactAction={writeEnabled ? onArtifactAction : undefined}
        loadArtifactDetail={loadArtifactDetail}
      />)}</>;
}

export function TimelineItem({ item, recentCompletion, writeEnabled, mutationBusy, onRetry, artifactAutoReveal = false, artifactTerminalCollapseMarker = null, onArtifactAction, loadArtifactDetail }: {
  item: TutorHistoryItem;
  recentCompletion: TutorRecentCompletion | null;
  writeEnabled: boolean;
  mutationBusy: string | null;
  onRetry: (turnId: string) => void;
  artifactAutoReveal?: boolean;
  artifactTerminalCollapseMarker?: string | null;
  onArtifactAction?: (request: TutorArtifactActionRequest) => void;
  loadArtifactDetail?: (artifact: TutorPublicArtifactItem) => Promise<TutorPublicArtifactItem>;
}) {
  if (item.kind === "process") return null;
  if (item.kind === "artifact") return <InlineArtifactMessage artifact={item} autoReveal={artifactAutoReveal} terminalCollapseMarker={artifactTerminalCollapseMarker} onAction={onArtifactAction} loadDetail={loadArtifactDetail} />;
  if (item.kind === "message") {
    if (item.role === "tutor") {
      return <TutorMessage item={item} recentCompletion={recentCompletion?.itemId === item.id ? recentCompletion : null} />;
    }
    return <article className="tutor-timeline-entry learner"><span className="tutor-timeline-label">你</span><div className="tutor-message-content"><p>{item.content}</p>{item.context_references.length > 0 && <TutorReferenceCards references={item.context_references} />}</div></article>;
  }
  if (item.kind === "error") {
    const migration = item.code === "TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN";
    return <article className="tutor-timeline-entry error"><span className="tutor-timeline-label">{migration ? "迁移提示" : "处理失败"}</span><div className="tutor-message-content"><strong>{migration ? "旧等待步骤已安全终止" : item.code}</strong><p>{migration ? "请在普通 composer 中发送一条新消息继续；Desktop 不会回退到旧 continuation 写入路径。" : item.message}</p>{item.recoverable && item.turn_id && <Button size="sm" variant="outline" disabled={!writeEnabled} busy={mutationBusy === `retry:${item.turn_id}`} onClick={() => onRetry(item.turn_id!)}>重试本轮</Button>}</div></article>;
  }
  return <TutorRequestHistory item={item} recentCompletion={recentCompletion?.itemId === item.id ? recentCompletion : null} />;
}

export function TutorRequestHistory({ item, recentCompletion }: { item: TutorInteractionRequestItem; recentCompletion: TutorRecentCompletion | null }) {
  const animateThinking = Boolean(recentCompletion?.streamedThinking);
  const thinking = useGraphemeTypewriter(item.public_thinking_text, {
    animate: animateThinking,
    initialText: recentCompletion ? (animateThinking ? recentCompletion.initialThinkingText : item.public_thinking_text) : item.public_thinking_text,
    resetKey: `request-thinking:${item.id}`,
    intervalMs: TUTOR_TEXT_REVEAL_INTERVAL_MS,
  });
  const promptTarget = recentCompletion && !thinking.complete ? "" : item.prompt;
  const promptReveal = useGraphemeTypewriter(promptTarget, {
    animate: recentCompletion !== null,
    initialText: recentCompletion ? "" : item.prompt,
    resetKey: `request-prompt:${item.id}`,
    intervalMs: TUTOR_TEXT_REVEAL_INTERVAL_MS,
  });
  const [expanded, setExpanded] = useState(recentCompletion !== null);
  const autoCollapsedRef = useRef(false);

  useEffect(() => {
    autoCollapsedRef.current = false;
    if (recentCompletion) setExpanded(true);
  }, [recentCompletion?.itemId]);
  useEffect(() => {
    if (!recentCompletion || autoCollapsedRef.current || !thinking.complete || promptTarget !== item.prompt || !promptReveal.complete) return;
    const timer = window.setTimeout(() => {
      autoCollapsedRef.current = true;
      setExpanded(false);
    }, TUTOR_THINKING_AUTO_COLLAPSE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [item.prompt, promptReveal.complete, promptTarget, recentCompletion, thinking.complete]);

  return <article className="tutor-timeline-entry tutor tutor-request-history" data-request-state={item.state} data-turn-id={item.turn_id}>
    <span className="tutor-timeline-label">Tutor 请求</span>
    <div className="tutor-message-content">
      {item.public_thinking_text ? <TutorThinking messageId={item.id} text={thinking.text} expanded={expanded} complete={thinking.complete} onExpandedChange={setExpanded} /> : null}
      <p className={`tutor-answer-text${recentCompletion && !promptReveal.complete ? " is-streaming" : ""}`}>{promptReveal.text}</p>
    </div>
  </article>;
}

export function TutorMessage({ item, recentCompletion }: { item: TutorHistoryMessage; recentCompletion: TutorRecentCompletion | null }) {
  if (item.runtime_output) {
    return <TutorRuntimeMessage item={item} output={item.runtime_output} />;
  }
  const animateThinking = Boolean(recentCompletion?.streamedThinking);
  const thinking = useGraphemeTypewriter(item.public_thinking_text, {
    animate: animateThinking,
    initialText: recentCompletion ? (animateThinking ? recentCompletion.initialThinkingText : item.public_thinking_text) : item.public_thinking_text,
    resetKey: `message-thinking:${item.id}`,
    intervalMs: TUTOR_TEXT_REVEAL_INTERVAL_MS,
  });
  const answerTarget = recentCompletion && !thinking.complete ? "" : item.content;
  const answer = useGraphemeTypewriter(answerTarget, {
    animate: recentCompletion !== null,
    initialText: recentCompletion ? "" : item.content,
    resetKey: `message-answer:${item.id}`,
    intervalMs: TUTOR_TEXT_REVEAL_INTERVAL_MS,
  });
  const [expanded, setExpanded] = useState(recentCompletion !== null);
  const autoCollapsedRef = useRef(false);

  useEffect(() => {
    autoCollapsedRef.current = false;
    if (recentCompletion) setExpanded(true);
  }, [recentCompletion?.itemId]);
  useEffect(() => {
    if (!recentCompletion || autoCollapsedRef.current || !thinking.complete || answerTarget !== item.content || !answer.complete) return;
    const timer = window.setTimeout(() => {
      autoCollapsedRef.current = true;
      setExpanded(false);
    }, TUTOR_THINKING_AUTO_COLLAPSE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [answer.complete, answerTarget, item.content, recentCompletion, thinking.complete]);

  return <article className="tutor-timeline-entry tutor" data-turn-id={item.turn_id ?? undefined}>
    <span className="tutor-timeline-label">Tutor</span>
    <div className="tutor-message-content">
      {item.public_thinking_text ? <TutorThinking
        messageId={item.id}
        text={thinking.text}
        expanded={expanded}
        complete={thinking.complete}
        onExpandedChange={setExpanded}
      /> : null}
      <SafeMarkdown markdown={answer.text} surface="message" streaming={Boolean(recentCompletion && !answer.complete)} className="tutor-answer-text" />
    </div>
  </article>;
}

export function TutorRuntimeMessage({ item, output }: { item: TutorHistoryMessage; output: TutorRuntimeOutput }) {
  const [expanded, setExpanded] = useState(false);
  const reasoningText = runtimeReasoningText(output);
  const answerText = output.final_answer_item?.text || item.content;
  return <article className="tutor-timeline-entry tutor" data-turn-id={item.turn_id ?? undefined}>
    <span className="tutor-timeline-label">Tutor</span>
    <div className="tutor-message-content">
      {reasoningText ? <TutorThinking
        messageId={item.id}
        text={reasoningText}
        expanded={expanded}
        complete
        onExpandedChange={setExpanded}
      /> : null}
      <SafeMarkdown markdown={answerText} surface="message" className="tutor-answer-text" />
    </div>
  </article>;
}

export function TutorRunningPlaceholder({ turn, hasText, text, complete, runtimeOutput }: {
  turn: TutorPublicTurn;
  hasText: boolean;
  text: string;
  complete: boolean;
  runtimeOutput: TutorLiveRuntimeOutputState | null;
}) {
  const [expanded, setExpanded] = useState(true);
  const reasoningText = runtimeReasoningText(runtimeOutput);
  const answerItem = runtimeOutput?.final_answer_item ?? null;
  const hasRuntimeContent = Boolean(reasoningText || answerItem?.text);
  return <article className="tutor-timeline-entry tutor tutor-running-placeholder" data-turn-id={turn.turn_id}>
    <span className="tutor-timeline-label">Tutor</span>
    <div className="tutor-message-content">
      {reasoningText ? <TutorThinking
        messageId={`active-${turn.turn_id}`}
        text={reasoningText}
        expanded={expanded}
        complete={runtimeOutput?.reasoning_items.every((item) => item.state === "completed") ?? false}
        running
        onExpandedChange={setExpanded}
      /> : null}
      {answerItem?.text ? <SafeMarkdown markdown={answerItem.text} surface="message" streaming={answerItem.state === "streaming"} className="tutor-answer-text" /> : null}
      {!hasRuntimeContent && (hasText ? <TutorThinking
        messageId={`active-legacy-${turn.turn_id}`}
        text={text}
        expanded={expanded}
        complete={complete}
        running
        onExpandedChange={setExpanded}
      /> : <div className="tutor-thinking-static" role="status" aria-label="think"><StateDot state="running" size={14} /><strong>think</strong></div>)}
    </div>
  </article>;
}

export function TutorThinking({ messageId, text, expanded, complete, running = false, onExpandedChange }: {
  messageId: string;
  text: string;
  expanded: boolean;
  complete: boolean;
  running?: boolean;
  onExpandedChange: (expanded: boolean) => void;
}) {
  return <DisclosureRow
    className="tutor-thinking-disclosure"
    title="think"
    icon={<StateDot state={running && !complete ? "running" : "positive"} size={14} />}
    expanded={expanded}
    onExpandedChange={onExpandedChange}
    contentId={`tutor-thinking-${messageId}`}
  ><p className={`tutor-thinking-text${complete ? "" : " is-streaming"}`} aria-live="off">{text}</p></DisclosureRow>;
}

export function TutorReferenceDraftChips({ references, disabled, onRemove }: { references: TutorComposerReference[]; disabled: boolean; onRemove?: (referenceId: string) => void }) { return <div className="tutor-reference-drafts" aria-label="待发送结构化引用">{references.map((reference) => <span key={reference.id} data-kind={reference.draft.kind}><span aria-hidden="true">{referenceIcon(reference.draft.kind)}</span><strong>{reference.label}</strong>{onRemove ? <button type="button" disabled={disabled} aria-label={`移除引用：${reference.label}`} onClick={() => onRemove(reference.id)}>×</button> : null}</span>)}</div>; }
export function TutorReferenceCards({ references }: { references: TutorContextReference[] }) { return <div className="tutor-reference-cards" aria-label="本条消息的结构化引用">{references.map((reference) => <article key={reference.reference_id} data-kind={reference.kind}><span aria-hidden="true">{referenceIcon(reference.kind)}</span><div><strong>{referenceTitle(reference)}</strong><small>{referenceSummary(reference)}</small></div></article>)}</div>; }
export function referenceIcon(kind: TutorContextReference["kind"] | TutorContextReferenceDraft["kind"]): string { return { lesson_selection: "§", exercise_feedback: "✓", execution_result: "⌘", review_feedback: "↺", teaching_session_message: "↗" }[kind]; }
export function referenceTitle(reference: TutorContextReference): string { return { lesson_selection: "课程选段", exercise_feedback: "练习反馈", execution_result: "执行结果", review_feedback: "复习反馈", teaching_session_message: "历史教学消息" }[reference.kind]; }
export function referenceSummary(reference: TutorContextReference): string {
  if (reference.kind === "lesson_selection") return reference.safe_excerpt;
  if (reference.kind === "teaching_session_message") return `${reference.role === "learner" ? "提问" : "讲解"} · ${reference.knowledge_key} · ${reference.message_summary}`;
  const summary = `${outcomeReferenceLabel(reference.outcome)} · ${Math.round(reference.score * 100)}% · ${reference.feedback_summary}`;
  return reference.kind === "execution_result" ? `${summary} · ${reference.execution_job_state}` : summary;
}
export function outcomeReferenceLabel(outcome: ExerciseAttemptOutcome): string { return { passed: "通过", failed: "未通过", timed_out: "超时", cancelled: "已取消", unavailable: "不可用", invalid: "无效" }[outcome]; }
