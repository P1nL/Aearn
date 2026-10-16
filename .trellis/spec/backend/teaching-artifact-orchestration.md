# Teaching Artifact Orchestration and Branch Scheduling

## Early result-evaluation failure

A result-evaluation Turn that fails before producing a public evaluation message must keep its original terminal outcome and diagnostic (for example `FAILED / TUTOR_CONTEXT_REQUIRED_OVERFLOW`). It must not publish the result Artifact timeline item or reclassify that failure as stale teaching authority merely because no message exists. Successful completion still requires the message-first atomic publication contract; a provider-unavailable path with a safe server result summary may publish only with that actual message.

## 1. Scope / Trigger

Apply this contract whenever code changes Tutor lesson-teaching decisions, provider-facing TeachingSession context, Learning Item candidate selection, atomic Tutor-message/checkpoint/Artifact persistence, clarification branches, continuation intents, timer/event continuation, or conversation snapshot branch projection.

This layer coordinates existing authorities. It does not replace Learning Item publication, Artifact lifecycle, TeachingSession/checkpoint, Lesson Gate, Review Item, Attempt, execution result, mastery, progress, or queue authority.

## 2. Signatures

### Versions and flags

```text
tutor.lesson-teaching@1.2.1
tutor_teaching_decision_v3
teaching_artifact_candidates_v1
teaching_action_receipt_v3
tutor_conversation_snapshot_v5

TUTOR_LEARNING_ARTIFACTS_ENABLED=false
TUTOR_ARTIFACT_TEACHING_MODE_ENABLED=false
```

Both flags must be true before the server advertises Artifact candidates or accepts an Artifact teaching decision. Historical reads remain available while the teaching flag is off.

### Python

```python
TeachingArtifactCandidateBuilder.build(
    *, scope: TeachingArtifactCandidateScope,
    available_capabilities: Sequence[str],
    learning_artifacts_enabled: bool,
    artifact_teaching_enabled: bool,
) -> TeachingArtifactCandidateSet

PostgresTeachingArtifactMaterializer.prepare(...) -> PreparedTeachingArtifact
PostgresTeachingArtifactMaterializer.create(
    prepared: PreparedTeachingArtifact, *, occurred_at: datetime
) -> LearningArtifactWriteResult

TutorClarificationBranchService.bind_learner_turn(...) -> TutorBranchTurnBinding | None
TutorClarificationBranchService.complete_turn(...) -> TutorBranchRecord | None

TutorContinuationIntentProducer.record_artifact_action(...)
TutorContinuationIntentProducer.record_demonstration_completion(...)
TutorContinuationIntentProducer.record_static_display_timer(...)
TutorContinuationIntentProducer.record_background_continuation(...)
TutorContinuationDispatcher.dispatch_next(...) -> ContinuationDispatchResult | None
```

### PostgreSQL

```text
tutor_conversation_branches
tutor_conversation_branch_events
tutor_conversation_branch_items
tutor_run_branch_scopes
tutor_continuation_intents
tutor_continuation_intent_events
```

## 3. Contracts

- Shared chat-direction semantics are instruction/test guidance, not a public enum: `continue_mainline` for related extensions; `answer_and_refocus` for a bounded answer followed by an explicit return to the current objective/focus and next executable step; `clarify_direction` for exactly one direction question; and `confirmed_switch` only after the learner explicitly rejects the old direction and names a new one.
- Precedence is latest learner input or explicit control plus current server planning/TeachingSession/checkpoint authority > recent messages > summary > memory/activity or persistent-thread association. Older continuity cannot restore a corrected, completed, refused, or replaced direction. Classification is semantic rather than keyword-based, and a related theme or implementation constraint must not be treated as drift.
- Direction handling creates no second authority. A non-blocking lesson turn may answer/refocus or wait through the existing composer; it cannot invent objective/focus/checkpoint/track/Artifact state. A blocking Artifact continues to use only the durable branch dispositions `answer_and_refocus`, `offer_switch`, and `confirmed_switch`.
- The server builds candidate authority from the exact current TeachingSession/checkpoint scope, the latest `published` Learning Item event, capability compatibility, Practice materialization, runtime readiness, and both feature flags. The provider receives bounded learner-safe handles only; private item content, answers, tests, rubrics, provider payloads, commands, paths, and runtime secrets are forbidden.
- Candidate projection evicts oldest optional `recent_teaching_units` before dropping eligible candidates and also compacts an oversized base when no candidates exist. Preserve the established 1,200-character compact JSON section contract; UTF-8 bytes feed the existing token estimator and numeric diagnostics, not a silently stricter 1,200-byte multilingual cap. Required authority/evaluation handles either fit intact or fail closed. Never return a truncated JSON fragment as required teaching context.
- Provider system-contract additions must fit the existing complete-request token budget, including serializer overhead and required TeachingSession authority. Compress redundant guidance rather than silently increasing policy limits or weakening tests. The current v5 provider action expresses response mode through `interaction.mode`; do not instruct it to emit the legacy top-level `learner_response_mode`. Guided artifact interaction requires `evidence_pause`.
- Known teaching semantic violations receive finite server-authored field/category repair guidance through the existing bounded same-model retry. Never expose rejected provider values or raw validation messages. A successful protocol run does not prove pedagogical correctness: verify that feedback agrees with the actual authoritative Artifact result, and separately test automatic continuation and learner-message recovery.
- KC introductions and result feedback must be grounded in exact public item/Artifact task evidence, not inferred from the Lesson title, old summaries or a generic correct/incorrect sentence. The loader emits candidate questions plus receipt-bound evaluation facts as required sources; use only validated public fields and an explicitly untrusted learner submission. The specialized exact-data serializer preserves all bounded JSON parts/options and fails if existing redaction changes them; it does not relax secret redaction, source-count or token-budget gates. Validate both initial introductions and wrong/remedial-result feedback in real runs.
- Parser repair and final admission share `teaching_response_mode_is_valid`: composer accepts only `check_understanding`/`wait_for_input` with a prediction, error-detection, misconception-contrast, or micro-transfer move; none forbids those two actions. Invalid current-v5 units emit the safe `action.interaction.mode:response_mode_invalid` issue before final admission, so the existing one same-model replacement can act. Keep the final Gate diagnostic and rejection matrix unchanged; do not normalize actions, invent Artifact authority, or increase retries.
- A v3 interaction has exactly one of these shapes: `none / none / null`, `composer / text_answer / null`, or `artifact / closed Artifact intent / exact li:<sha256> handle`. Unknown modes, intents, handles, extra fields, stale scope, or impossible pairings reject the entire public decision before a Tutor message is published.
- The Decision Gate revalidates mode, intent, handle, scope, feature flags, publication state/version, capability set, Practice authority, and runtime profile. It never trusts a provider-selected kind, payload, exercise identity, owner version, or learner-visible content.
- One caller-owned PostgreSQL transaction commits the accepted Tutor public message, next Teaching checkpoint/session CAS, teaching action receipt, Artifact row, Artifact event, conversation `item_added` reference, and source Turn terminalization. Any failure rolls back every public write.
- Artifact materialization creates only the interaction facade. It must not create Attempt, score, Gate/Review completion, mastery, or progress evidence. Owner actions delegate through the exact registered authority and fail closed when no safe adapter exists.
- A normal learner message while an exact blocking Artifact is active binds to a durable depth-one clarification branch anchored to that Artifact, TeachingSession, and checkpoint lineage. Branch membership is explicit and append-only; nested branches are forbidden.
- Branch response disposition is closed: `answer_and_refocus`, `offer_switch`, or `confirmed_switch`. An unrelated question is answered and then refocused. A topic switch requires an explicit offer followed by a typed confirmation control.
- Hint or direct-answer assistance requires an exact authoritative Hint/Teaching receipt in the same user, conversation, track, knowledge, Artifact, and session scope. Text inference or unreceipted assistance is forbidden.
- Continuation producers persist facts only and never call a provider. The fixed priority is learner message > explicit Artifact action > expected interactive event > static display timer > background continuation. At most one claim and one publishable foreground Tutor Turn may exist per conversation.
- A pending learner input, active foreground run, or active clarification branch blocks automatic continuation. Static timers and background continuation are Guided-mode only. Stale claims, Artifact/session versions, checkpoint ancestry, or scope are cancelled or rejected fail closed.
- Artifact/result continuations resume on the mainline only after the branch resolves. Reconnect reconstructs the branch from snapshot v5; v3/v4 compatibility remains additive for conversations without branch history.
- Export contains bounded branch/continuation summaries only. Reset/delete removes user-owned branch and continuation children in dependency order. No private source payload or provider reasoning is exported.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Both Artifact flags are not enabled | candidate set empty; Artifact interaction rejected; historical reads preserved |
| No compatible published candidate for requested edit/run/review/query/demo/respond intent | reject the whole decision before message persistence |
| Unknown/stale handle, publication, capability, Practice, runtime, session, checkpoint, track, progress, or assignment identity | fail closed; no message/checkpoint/receipt/Artifact partial write |
| Artifact/event append fails after message preparation | transaction rollback; source Turn ends with a safe authority diagnostic |
| Learner message races timer/background/event/action continuation | learner Turn wins; lower-priority claim remains pending, is released, or is superseded deterministically |
| Two continuation claimants race | at most one valid claim generation; loser receives no runnable Turn |
| Automatic continuation in free-reading mode | deny/cancel without provider execution |
| Branch input crosses user/conversation/track/Artifact scope | not found or stale/conflict without revealing foreign existence |
| Nested branch or stale checkpoint ancestry | reject; do not attach the Turn to a guessed branch |
| Hint/direct answer lacks exact receipt | reject branch completion; keep branch/Artifact authority unchanged |
| Topic-switch confirmation has no prior offer | reject typed transition |
| Reconnect after branch creation | snapshot v5 contains the exact anchor, state, disposition, rounds, and item membership |
| Reset/export/delete | no private payload in export; dependent branch/continuation rows are removed safely |
| Session authority replacement with old active branches | atomically create successor, block old session, append authority_superseded and retire branches; keep items/rounds/progress unchanged |
| Supersession without direct same-scope successor, changed authority, blocked old session, or with live old run | owner/SQL reject; no partial event, branch or session changes |
| Supersession replay / stale CAS | exact original replay returns the same event; altered scope/version/event conflicts |

Authority retirement uses `superseded`, never `resolved`. Schema fragment 210 is an incremental reentrant extension; retirement events have no learner/provider source input or response. Keep both active-branch guards unchanged. Public active/resolved groups remain V1; only superseded uses group V2 plus `superseded_at` and summary V2. Historical reconciliation requires a bounded proven predecessor chain, read-only dry-run, exact scope/version review and owner writes; it must not dispatch stale intents or reopen completed progress.

## 5. Good / Base / Bad Cases

- **Good:** A published knowledge-check handle is advertised under the exact checkpoint. The provider selects `artifact / structured_answer / li:<sha256>`, the gate revalidates it, and one transaction publishes the Tutor message, checkpoint, receipt, Artifact, Artifact event, timeline reference, and terminal Turn.
- **Good:** A learner asks a clarification while the Artifact waits. The learner Turn binds to one depth-one branch, the Tutor answers and refocuses with any assistance receipt recorded, and the later Artifact result continues on the mainline.
- **Good:** An explicit Artifact action, timer, and background intent coexist. The explicit action is claimed first; a newly queued learner message preempts before any automatic Tutor Turn is published.
- **Base:** Artifact teaching is disabled. Skill history and existing Artifact/branch snapshots remain readable, but candidate context is empty and v3 Artifact decisions fail closed.
- **Bad:** Letting the provider invent an exercise identifier, sending private Learning Item content in prompt context, or truncating candidate JSON so authority becomes ambiguous.
- **Bad:** Publishing a Tutor message before creating the Artifact in a separate transaction.
- **Bad:** Letting a timer invoke the provider directly, choosing continuation by arrival order, or treating browser-local branch state as authority.
- **Bad:** Resolving a branch from free text or granting a hint/direct answer without an exact policy receipt.

## 6. Tests Required

- Skill catalog and strict-contract tests must prove 1.1.0 and 1.2.0 are unchanged, 1.2.1 compiles with semantic direction-drift evals, decision v3 rejects unknown/extra fields, and every interaction mode/intent/handle pairing is exact.
- Candidate tests cover feature-off behavior, publication states, capability mismatch, stale scope, private-field exclusion, deterministic ordering, the eight-item cap, and provider-context representation within the fixed budget.
- Atomic PostgreSQL tests cover success, exact Learning Item/Practice materialization, receipt v3 linkage, stale publication between context and commit, event failure after message preparation, idempotency, and rollback of message/checkpoint/Artifact/Turn state.
- Branch tests cover cross-scope rejection, depth-one enforcement, additional rounds, answer/refocus, offer/confirm switch, positive Hint receipt, direct-answer receipt, stale lineage, branch resolution, mainline result continuation, and snapshot reconnect.
- Continuation tests cover all five priority classes, two competing claimants, lease generation/expiry, learner preemption, pending-input and active-foreground blocking, Guided-only timer/background behavior, producer no-provider behavior, stale authority cancellation, and one publishable Turn.
- Cutover/export/reset tests classify branch and continuation tables exhaustively, redact private data, and remove children before parents.
- Run focused PostgreSQL tests serially, then the complete API suite, Ruff, Mypy, dependency lock validation, Trellis task validation, and `git diff --check`. Real provider smoke and Docker conformance require separate approval.

## 7. Wrong vs Correct

### Wrong

```python
decision = provider.decide(context)
message = repository.publish_message(decision.public_message)
artifact = repository.create_artifact(decision.interaction.artifact_handle)
if timer_due:
    provider.decide(timer_context)
```

This trusts provider identity, separates public writes, leaks partial state on failure, and lets a timer bypass durable scheduling and foreground arbitration.

### Correct

```python
candidates = candidate_builder.build(
    scope=current_scope,
    available_capabilities=capabilities,
    learning_artifacts_enabled=settings.tutor_learning_artifacts_enabled,
    artifact_teaching_enabled=settings.tutor_artifact_teaching_mode_enabled,
)
accepted = decision_gate.accept(decision, candidates=candidates)

with conn.transaction():
    prepared = materializer.prepare(step=accepted.teaching_step, **exact_fences)
    terminal = repository.prepare_terminal_teaching_commit(accepted, prepared)
    repository.commit_terminal_teaching_effects(terminal)

continuation_producer.record_artifact_action(**event_identity)
dispatcher.dispatch_next(**conversation_claim)
```

The correct path advertises only server-proven handles, validates the exact decision, commits every public teaching effect atomically, records continuation as a durable fact, and lets one deterministic arbiter create the next mainline Turn.


## Published demonstration contract

- Materialize `demonstration_v2` only from the selected published Learning Item handle; provider output never owns source, steps, event, or duration.
- Static fallback duration is deterministic and 6-30 seconds per materialized step; oversized static source may be split within the descriptor bounds.
- Completion is exactly-once and receipt-backed. Exact Preview event and visible-clock evidence are mutually exclusive; Preview nonce/generation/sequence must fit the native bridge and receipt columns, and an event payload must fit the shared bounded bridge shape.
- Demonstration completion must not create Attempts, mastery evidence, or track progress. Continuation priority is expected-event for interactive and static-timer for static, always below learner input.

## Learner teaching Retry binding

Retry must not only inherit LearningTrack scope. Before admitting a retry of a learner-message teaching run, lock conversation then verify the original session/checkpoint/track/assignment/document authority remains current. Bind the new input message and revision to a new learner stimulus and teaching scope in the same API idempotency transaction as the new run and queue control event; return teaching_scope. Stale authority or binding failure rolls back all new records. Non-learner control/domain stimuli must be reissued via current teaching controls rather than masquerading as learner messages. Historical unbound retries are not rewritten.
- 2026-09-10: Preserve TeachingStepDecision.public_message whitespace/Markdown exactly (after outer trim). Collapsing spaces/newlines made equal provider message fields unequal during TutorDecision assembly. Regression includes multiline paragraphs and indented code. No weakening of exact-message validation.


## Programmatic backend acceptance inputs（2026-10-16）
无模型Artifact后端验收的programmatic TeachingStepDecision也必须遵守已发布教学合同：v2/v3教学单元使用2..4个不同的允许teaching_moves，public_message与这些动作一致；artifact interaction保持真实candidate的intent/handle。原DTO构造成功不代表SQL receipt CHECK必然接受，不能仅依赖DTO当前max_length=4而漏掉下限。

- 错误：仅micro_transfer一项，绕过provider/parser直接进入complete_run；原teaching_action_receipt_v3的version_shape会拒绝。
- 正确：真实Python绑定练习的无模型DATA可用targeted_explanation+micro_transfer及对应简短规则说明/练习提示；离线抽取实际operator构造验证2个不同允许动作、artifact语义，随后原无插桩transaction/完整constraint回滚验收。
- 不为测试输入错误修改产品DTO、旧SQL、CHECK或TTL；保留原失败证据。完整后端DATA验收成功仍不等于真实Tutor模型、PRIVATE质量链或P7整体完成。

该输入修正的C13真实验收已于2026-10-16通过：原complete_run、最终即时约束检查及scope退出完成；原action/consumer/Artifact实际同事务写入后完整回滚。证据见题库任务research/p7-consumer-public-contract-fix-design-20261015.md§11；仍标为programmatic DATA而非模型输出。
