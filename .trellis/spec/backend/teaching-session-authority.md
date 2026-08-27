# Teaching Session Authority 与 Closed Teaching Loop

## 1. 适用范围 / Trigger

当一条长期 LearningTrack Tutor conversation 需要按知识点分段教学，或代码触及 teaching session/checkpoint、Tutor Turn admission、required context、closed teaching action、Harness commit fence、Action Shelf、public projection、cutover inventory、local export/reset/delete 时，必须遵守本规范。

TeachingSession 是同一 track conversation 内的 durable authority segment，不是第二条 conversation，也不得从聊天正文、Lesson 标题或 Desktop pointer 猜测重建。

## 2. Signatures

### HTTP

```text
GET  /api/learning-tracks/{track_id}/teaching-sessions?user_id={uuid}
GET  /api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}?user_id={uuid}
POST /api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}/open
POST /api/learning-tracks/{track_id}/teaching-sessions/{session_id}/actions
```

mutation 使用 `client_action_id` / `Idempotency-Key` 与 expected session/track/progress/assignment versions。客户端 `admit_run` 不是 admission authority；服务端根据 closed control policy 决定是否创建 run。

### Skill / provider

```text
tutor.lesson-teaching@1.1.0
required context section: TEACHING_SESSION
provider action: teaching_step
output contract: tutor.teaching-step-decision.v2
```

```python
TeachingStepDecision(
    action: TeachingAction,
    objective_id: str,
    focus_id: str,
    source_handles: tuple[str, ...],
    public_message: str,
    focus_resolution: TeachingFocusResolution,
    pause_kind: TeachingPauseReason,
    teaching_moves: tuple[TeachingMove, ...],  # 2..4 unique
    learner_response_mode: TeachingLearnerResponseMode,
    escalation_hint: str | None,
)
```

### Python

```python
TeachingSessionRepository.bind_learner_message_run(...) -> dict[str, object] | None
TeachingSessionRepository.assert_run_scope_current(...) -> Mapping[str, object]
TeachingSessionRepository.teaching_context(...) -> dict[str, object] | None
TeachingSessionRepository.admit_control_run(...) -> dict[str, object]
TeachingSessionRepository.admit_domain_event_run(...) -> dict[str, object]

reduce_teaching_checkpoint(...) -> TeachingCheckpointState
build_teaching_action_shelf(...) -> TeachingActionShelfV1
```

### PostgreSQL

User-owned tables:

```text
tutor_teaching_sessions
tutor_teaching_session_checkpoints
tutor_run_stimulus_events
tutor_run_teaching_scopes
tutor_teaching_action_receipts
```

## 3. Contracts

- 一条 LearningTrack 只有一条长期 learner-visible Tutor conversation；TeachingSession 只拥有一个 knowledge-point segment。
- session 冻结 user/track/conversation/knowledge、track/plan/progress、active Lesson assignment 与 LessonDocument authority。exact scope 最多一条 `active | paused` current session；authority 变化时旧 session 追加 `authority_pause` checkpoint 并置为 `blocked`，新 session 以 `predecessor_session_id` 建立 successor，不改写旧 authority。
- checkpoint 是 append-only predecessor chain；`current_checkpoint_id + version` 以 CAS 推进。checkpoint、stimulus、run scope 与 action receipt 禁止普通 UPDATE/DELETE。
- 每个 teaching-scoped fresh run 恰有一个 immutable stimulus：`learner_message | teaching_control | domain_event`。learner stimulus 引用 exact input receipt；control/event 不伪造 learner message，不使用 proactive origin。
- `TEACHING_SESSION` 是 required context，位于 current input/current structured event 之后、optional history 之前。它只含 exact session/stimulus、bounded objective/focus/questions/covered summary、authority versions、pause/action policy 与 allowlisted handles；不可表示时在 provider 前 fail closed。
- `teaching_control | domain_event` 没有伪造的 `current_input`，但必须从 `tutor_run_teaching_scopes` 按 exact `teaching_session_id + user_id + conversation_id` 加载当前 run 之前的 bounded learner-visible messages 作为 optional `RECENT_MESSAGES`。顺序使用 frozen `session_version + scope.created_at + run_id`，不得混入 legacy group、predecessor/successor session、其他 knowledge 或未来消息。provider 对 `continue/resume` 必须从最新可见教学消息继续，不能重新开始或近义复述已讲解内容；只有 `change_example`、checkpoint remediation 或 summary authority 可以要求重述/重构。
- provider 必须先选择 exact `tutor.lesson-teaching@1.1.0`，再返回且只返回一个 strict `tutor.teaching-step-decision.v2` `teaching_step`。closed action 为 `orient | explain_concept | answer_question | show_example | compare_examples | check_understanding | recommend_practice | explain_feedback | remediate_prerequisite | summarize_progress | recommend_pause | wait_for_input`；还必须提供 2--4 个互不重复的 closed `teaching_moves` 与显式 `learner_response_mode=none | composer`。历史 `1.0.0` bundle 完全不可变，provider parser 可兼容缺少 v2 字段的旧 payload，但 v1.1 decision gate 必须拒绝。
- focus resolution 只能是 `stay | push_child | resolve_and_resume_parent | replace_objective | abandon_branch | wait`，且 focus identity 必须来自 active/suspended/objective/current stimulus allowlist；模型不得创建任意 focus、UI、mastery、completion、unlock 或 next knowledge key。
- terminal commit 在同一 PostgreSQL transaction 内完成：重新验证 lease/run/session/checkpoint/track/progress/assignment/document/stimulus，append next checkpoint，CAS session，insert safe action receipt，写 learner-visible Tutor message，terminalize run/outbox。任一步失败全部回滚。
- 每个成功 stimulus 最多提交一个主要 teaching action，并写 `soft_pause | evidence_pause | authority_pause | session_pause | completion_pause`；terminal 后没有新 stimulus 时不得自动 admission 下一 Turn。
- `free_reading` learner message 只允许 reactive finite answer；`continue/return_focus/change_example` 不能绕过服务端 policy 触发主动教学。只有显式 `escalate_guided` 才切 Guided 并 admission 一个 bounded Turn；Free Reading resume 不自动调用 provider。
- `TeachingActionShelfV1` 完全由服务端生成：最多一个 primary、三个 visible secondary；active runtime、blocking request 与普通 shelf 互斥。只有 checkpoint 明确推荐 `continue` 才投影 Continue；`learner_response_mode=composer` 投影 `respond_in_composer`。没有 descriptor 时返回真正的空 shelf，Desktop 不挂载 shelf DOM或补 placeholder。completion shelf 只提供显式 next/navigation，不投影无法执行的 pause action。
- completed progress 必须对应 `summarize_progress + completion_pause`。session 留在 completed 状态；只有 `enter_next_knowledge` typed control 才重新读取最新 roadmap/availability、推进 track pointer、open/resume 下一 session 并 admission 一个 first-unit run。
- public projection/trace/export 只能包含 stable IDs、versions、enum、bounded summaries 与 hashes。禁止 prompt、reasoning、provider body、raw checkpoint/authority JSON、完整问题/提交、hidden tests/rubric、命令、路径或 secrets。
- 五张表全部进入 cutover exhaustive inventory 与 local summary/export/reset/delete；删除先 action receipt，再 run scope/stimulus/checkpoint/session，并在同一事务使用 deferred `NO ACTION` lineage FK 与 transaction-local purge capability。

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Cross-user / cross-track / cross-conversation read or mutation | scoped `404` 或 `409 TEACHING_AUTHORITY_CONFLICT`；不泄露 foreign existence |
| Missing/oversized required teaching context | `TUTOR_TEACHING_SESSION_STALE` 或 `TUTOR_TEACHING_SESSION_UNREPRESENTABLE`；provider 不调用 |
| control/domain run 已有同 session 历史但 `RECENT_MESSAGES` 为空，或混入 legacy/其他 session/future message | context continuity contract failure；修复 loader/test，不通过提示词猜测补救 |
| Unknown action、extra field、unknown handle 或 unlisted focus | policy denial；无 message/checkpoint/receipt |
| teaching run 未选择 exact Skill 或未返回 `teaching_step` | `teaching_skill_required` / `teaching_step_required` policy denial |
| completion pause 无 completed progress，或 completed progress 未使用 completion pause | `teaching_completion_pause_invalid`；无 durable commit |
| Expected session/track/progress/assignment version stale | `409 TEACHING_AUTHORITY_CONFLICT`；无新 run/message/checkpoint |
| Provider 返回后 session/checkpoint/assignment/progress 已变化 | source run durable `cancelled` + `teaching_authority_stale`；不公开旧 output |
| Free Reading 调用 guided-only `continue/return_focus/change_example` | `400 TEACHING_ACTION_INVALID`；不 admission run |
| Control/domain admission 会产生竞争 foreground run | `409 TEACHING_AUTHORITY_CONFLICT` |
| 同 idempotency key 对应不同 immutable request | `409 IDEMPOTENCY_CONFLICT` |
| 普通 UPDATE/DELETE checkpoint/stimulus/scope/receipt | PostgreSQL `23514` append-only trigger rejection |
| reset/delete 不在 exact user purge scope | trigger/FK rejection |

## 5. Good / Base / Bad Cases

- **Good:** Guided open 创建 session/checkpoint 与一个 `open_session` teaching-control run；fake provider 两阶段选择 exact Skill，再提交一个 `explain_concept + soft_pause`，原子写 message/checkpoint/receipt，且不会自动创建第二个 run。
- **Good:** 第一个 teaching-control run 没有 prior session message；第二、第三次 `continue/resume` 分别看到同 session 的 1、2 条 prior messages，provider 在上一讲解后推进到示例/比较/理解检查。legacy history 与其他 TeachingSession 消息保持不可选。
- **Good:** Free Reading learner message 绑定真实 message/input receipt，得到一个 reactive answer 后仍保持 Free Reading；显式 `escalate_guided` 才创建下一个 control run。
- **Good:** progress version 变化后，旧 active session 追加 authority-pause checkpoint 并置为 blocked；successor 冻结新 authority。completed evidence 只允许 `summarize_progress + completion_pause`。
- **Good:** `enter_next_knowledge` 使用最新 expected versions 和 candidate key，重新验证 active plan/availability 后复用同一 conversation，推进 track pointer 并只 admission 一个 next-session run。
- **Base:** 旧 conversation/history 没有 teaching metadata 时仍可读，不做聊天正文 backfill；未显式 open 前可保持 legacy-compatible path。
- **Bad:** 根据 learner 文本猜 `continue`，插入伪 learner message，或以 proactive origin 处理用户控制。
- **Bad:** 因 control/domain 没有 current learner input 就把 `recent_messages` 留空，只反复发送同一个 objective/checkpoint summary，导致每次 `continue/resume` 重新讲同一段定义。
- **Bad:** 让客户端决定 Action Shelf label/target、mode mutation、mastery/completion/next node，或允许 provider 引用任意 focus/handle。
- **Bad:** 先公开 message，再单独写 checkpoint/receipt；后续 stale/DB failure 会产生不可恢复的分叉 authority。

## 6. Tests Required

- PostgreSQL bootstrap twice：五张表、owner/scope FK、partial unique `active | paused` predicate、exact-one CHECK、append-only trigger、source-stimulus deferred `NO ACTION` FK。
- Skill/catalog/provider：published Skill identity、strict good/base/bad schema、extra field、unknown action/handle/focus、message exact binding、non-teaching compatibility。
- Context：exact session/stimulus/handles、current-input priority、default budget 可表示、低预算 provider-before fail closed、optional context eviction 回归；control/domain 的第 N 次 run 精确选择同 session 前 N-1 次 learner-visible messages，并排除 legacy/其他 session/future rows。
- Loop/reducer：one stimulus -> one action -> one pause、focus push/resume/abandon/replace/wait、bounded stack/questions、resolved child question 移除、无新事件调用数稳定。
- Free Reading：reactive answer mode 不变；guided-only control bypass 拒绝；显式 escalation 创建一个 control run；pause/resume 不错误触发 provider。
- Completion：authority refresh successor、completion pause 原子 commit、无自动 next、stale roadmap conflict、显式 latest-roadmap transition 仍使用同一 conversation。
- Governance/privacy：receipt append-only、export 无 public message/provider/protected body、reset child-to-root、cutover inventory exhaustive、trace/redaction regression。
- 质量门：focused tests、完整 API pytest、Ruff、Mypy、bootstrap twice、Trellis validate 与 `git diff --check`；默认 fake provider，真实 provider 需再次明确批准。

## 7. Wrong vs Correct

### Wrong

```python
knowledge_key = infer_from_chat(conversation.messages)
message_id = repository.insert_message(role="learner", content="continue")
run = repository.create_run(origin="proactive")
provider_result = provider.decide(...)
repository.insert_public_message(provider_result.text)
repository.update_checkpoint_later(...)
```

### Correct

```python
control = TeachingControlStimulus(
    control_key="continue",
    client_action_id=client_action_id,
    expected_session_version=session_version,
    expected_track_version=track_version,
    expected_progress_version=progress_version,
    expected_assignment_version=assignment_version,
)

run_scope = teaching_sessions.admit_control_run(
    authority=authority,
    session=current_session,
    stimulus=control,
)

# provider 只能返回 one closed teaching_step；commit transaction 同时写
# next checkpoint + session CAS + safe receipt + public message + terminal run。
assert run_scope["origin"] == "interactive"
```

正确路径不伪造 learner message，冻结 exact authority，只允许 server-provided handles/focus，并可在任何 stale fence 上无公开副作用地拒绝。

## 场景：Conversation teaching groups 与 exact 历史消息引用（2026-08-23）

### 1. 适用范围 / Trigger

- 触发：修改 conversation snapshot 的 `teaching_sessions[]`、历史教学分段、`tutor_message_context_references` 或模型上下文中的历史消息解析。

### 2. Signatures

`TeachingSessionRepository.conversation_projection(user_id, conversation_id)` 返回最多 50 个 safe session group；每组额外含由 `tutor_run_teaching_scopes` 投影的唯一、bounded `turn_ids`。`TutorInputRequest.context_references[]` 新增 `teaching_session_message { learning_track_id, knowledge_key, teaching_session_id, message_id }`。

PostgreSQL 继续复用 user-owned append-only `tutor_message_context_references`，`reference_kind` 增加 `teaching_session_message`；该 kind 的 document/attempt/review/exercise FK 列必须全部为 NULL，不新增 user-owned table。

### 3. Contracts

- grouping 只从 durable run scope 取得 turn ownership，不根据聊天正文、标题、时间邻近或 DOM 顺序猜测。
- exact historical reference 在接受当前 learner input 的同一事务内校验 source session/message 的 user、track、conversation、knowledge 与 source turn scope；任一不匹配 fail closed。
- public saved reference 只包含 IDs、role、中性 `message_summary`、时间、version/hash；完整历史 `message_content` 不写入 public safe payload、response、timeline card 或 export。
- 模型上下文使用独立 `read_for_context`，在每次加载时重新按 exact IDs 与同 conversation authority 解析完整 learner-visible message；解析失败为 stale reference，provider 前拒绝。
- destination current Turn 的 knowledge scope 不因引用历史 knowledge 改变；cross-session reference 只是 confirmed fact source，不伪造 current focus/stimulus。

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| foreign user/track/conversation/session/message | scoped 404/409；不泄露 foreign existence |
| message 不属于 session 的任一 `turn_id` | `CONTEXT_REFERENCE_NOT_FOUND`，整个 input mutation 回滚 |
| public safe payload 含完整消息正文 | contract/privacy failure |
| internal context 二次解析时 source authority 消失 | `CONTEXT_REFERENCE_STALE`；provider 不调用 |
| unknown/extra reference field | request validation error |
| duplicate exact session/message reference | `CONTEXT_REFERENCE_INVALID` |

### 5. Good / Base / Bad Cases

- Good：历史 Tutor message 的 exact IDs 经 session/run scope 校验，公开 response 只有中性摘要，内部 required fact 含受控解析的原消息。
- Base：旧 conversation 无 teaching metadata 仍可读并进入 legacy group，不猜测 backfill。
- Bad：把完整旧问题复制进 current learner content，或把完整正文存入 `safe_payload_json`/export。

### 6. Tests Required

- PostgreSQL：合法 exact reference、随机/foreign session、message/session scope mismatch、append-only、bootstrap twice。
- Context：public response/export 不含完整消息；internal required fact 能取得 exact source content；stale 二次解析 provider-before fail closed。
- Conversation projection：turn IDs bounded/unique，list group 的 `action_shelf=null` 与 `allowed_actions=[]`，protected fields 不出现。
- 全部变更仍经过 focused tests、完整 API pytest、Ruff、Mypy、cutover inventory/reset/delete 与 `git diff --check`。

### 7. Wrong vs Correct

#### Wrong

`reference = { "content": historical_message.content }`，或按消息正文猜所属 session。

#### Correct

客户端只发送 `teaching_session_id + message_id`；repository 验证 exact source turn scope，公开 projection 只存中性元数据，内部 context loader 才按 authority 读取正文。

## 场景：Durable domain event 与 checkpoint-backed teaching summary（2026-08-23）

### 1. 适用范围 / Trigger

- 触发：Gate/Attempt terminal、Review finalization、progress completion、Lesson assignment migration，或 teaching context/compaction/跨日恢复逻辑变化。

### 2. Signatures

`TeachingDomainEventAdapter.admit_gate_terminal(...)`、`admit_review_terminal(...)`、`admit_progress_changed(...)`、`admit_assignment_changed(...)` 只读取 owner 已提交的 durable authority，并输出 exact `DomainEventStimulus(kind, source_id, source_version, safe_handles)`。`TeachingSessionRepository.structured_summary(...)` 从 current append-only checkpoint 生成 `teaching_session_summary_v1`；`teaching_message_semantics(...)` 返回 correction/unresolved message IDs 供 compaction fence 使用。

### 3. Contracts

- domain owner 先原子提交 score/mastery/schedule/progress/assignment；adapter 不重算业务结果，只校验 durable source identity/version。
- duplicate identity 先读取既有 stimulus/run receipt；不得先创建新 run 再依赖 unique violation 回滚。
- authority 变化通过既有 `open_or_resume` 阻断 predecessor 并创建 successor；没有 open teaching session、旧 source version 或竞争 foreground run 时 fail closed，不伪造 learner message。
- Gate completion coalesce 为 `progress_changed` 一次 bounded Turn，并保留 gate safe handle；非 completion Gate 使用 `gate_terminal`。Review 与 assignment 使用各自 immutable receipt/assignment version。
- teaching summary 不新增重复表：checkpoint 本身就是 predecessor-linked append-only source。summary 必须重新计算 checkpoint source hash、验证 session/current checkpoint/version 与 authority snapshot，失配即 `TeachingSessionConflict`。
- required `TEACHING_SESSION` 使用 <=1200 字符 compact projection；完整 structured summary 进入 optional `WORKING_SUMMARY`。current summary 优先于 generic conversation summary，最多附带一个 exact predecessor summary，不默认重放全量历史。
- unresolved question source message、focus 中 exact `message:*` handle 与当前 session 最新 learner input 进入 `protected_message_ids`；旧 summary 不得退休这些消息或覆盖 current input。
- Free Reading learner input 仍只允许 reactive action；typed `domain_event` 可使用 bounded evidence/completion actions，但不隐式切换 session mode。

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| durable source 不存在、跨 user/track 或 source version stale | `event_status=ignored`，无 run/stimulus/message |
| exact domain event replay | 返回同一 run/stimulus，`idempotent_replayed=true` |
| session authority 变化且无 active foreground run | predecessor `authority_pause + blocked`，successor 冻结新 authority并 admission 一次 |
| checkpoint/session/version/authority/hash 不一致 | `TeachingSessionConflict`；summary 不进入 context，provider 前 fail closed |
| required teaching projection超界 | `TUTOR_TEACHING_SESSION_UNREPRESENTABLE`；不得靠截断 required authority 继续 |
| Free Reading 普通 learner turn 返回 `summarize_progress` | `free_reading_action_invalid` |
| Free Reading typed completion event 返回 `summarize_progress + completion_pause` | 允许一次 closed commit，mode 保持 `free_reading` |

### 5. Good / Base / Bad Cases

- Good：required Gate 完成使 progress version 增加；旧 session blocked，successor 收到一个 `progress_changed` run；重复 source version 返回同一 run。
- Good：assignment migration 激活新 version 后创建 successor 与一个 `assignment_changed` run，旧 assignment/session 只读。
- Base：没有 teaching session 时 Review/Gate 仍正常提交 owner authority，adapter 返回 ignored，不影响主事务。
- Bad：把完整 submission/rubric/provider body 放进 `safe_handles`，或为 progress 与同一 Gate completion 并发创建两个前台 Turn。

### 6. Tests Required

- `test_tutor_adaptive_teaching_evals.py`：Gate completion、assignment migration、duplicate/stale source、summary hash fencing、closed focus path、explicit next。
- Review/Gate/Lesson owner regression：terminal authority 不因 adapter ignored/duplicate 回滚；重复 finalization/migration 保持 owner 幂等。
- Context/compaction：compact required source 可表示；current summary ordering；protected correction/unresolved IDs；stale summary provider-before fail closed。
- Full serial PostgreSQL pytest、Ruff、Mypy、bootstrap twice、Desktop tests/build、三视口 Browser smoke、cutover/export/reset/privacy、Trellis validate 与 diff hygiene。

### 7. Wrong vs Correct

#### Wrong

先创建 run，再插入 domain stimulus并期待 unique index处理重复；或另建 mutable summary 表复制 checkpoint 状态。

#### Correct

先以 `(session,event_kind,source_id,source_version)` 查 exact receipt；只在 durable source/current authority 可证明时创建 run。summary 从 validated append-only checkpoint 投影，hash/source lineage 不匹配立即 fail closed。

## 场景：Teaching step v2、recent-unit gate 与条件式 Shelf（2026-08-27）

### 1. 适用范围 / Trigger

- 触发：修改 `tutor.lesson-teaching` 版本、`TeachingStepDecision`、decision gate、teaching receipt、required `TEACHING_SESSION` 投影、checkpoint recommendation 或 Desktop Action Shelf。

### 2. Signatures

- Skill：exact `tutor.lesson-teaching@1.1.0`，output contract `tutor.teaching-step-decision.v2`；`1.0.0` 三个 bundle 文件及 hash 不得修改。
- Provider：`teaching_moves: tuple[TeachingMove, ...] | None`、`learner_response_mode: none | composer | None`；optional 只为解析历史 payload，v1.1 gate 要求非空。
- DB：`tutor_teaching_action_receipts(teaching_moves_json, learner_response_mode, schema_version, policy_version)`；新 row 写 `teaching_action_receipt_v2` / `lesson_teaching_policy_v2`。
- Context：`recent_teaching_units` 最多四项，每项仅含 action、focus ID、moves、response mode、public-message hash 与 schema version。

### 3. Contracts

- 每个 v2 单元必须有 2--4 个互不重复的 closed moves：`targeted_explanation | worked_example | counterexample | misconception_contrast | guided_derivation | prediction | error_detection | micro_transfer | learner_feedback`。
- `composer` 只允许 `check_understanding | wait_for_input`，且必须包含 `prediction | error_detection | micro_transfer | learner_feedback` 至少一种诊断 move；`none` 不允许这两个 action。`change_example` control 的 decision 必须包含 `worked_example | counterexample`。
- recent-unit projection 不保存或复制消息正文；required projection 使用 compact authority subset并保持既有 1,200 字符上限。不能增加全局 budget 来掩盖重复字段造成的 overflow。
- Continue 若与最近 v2 unit 的 public-message hash 相同，或 objective/focus/moves/response mode 的策略签名相同，必须在 durable commit 前拒绝 `teaching_unit_not_advanced`。
- reducer 先处理 runtime/request/evidence/session/completion/Free Reading authority，再解释 response mode。只有推荐 `continue` 才显示主 Continue；composer 显示 `respond_in_composer`；无 descriptor 时 shelf 为空。

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| v1.1 decision 缺少 moves/mode，moves 少于 2、多于 4 或重复 | policy denial；无 message/checkpoint/receipt |
| composer 搭配非 check/wait，或没有诊断 move | policy denial；无 durable commit |
| none 搭配 check/wait | policy denial；无 durable commit |
| `change_example` 未实际改变为 worked/counterexample | policy denial |
| Continue 重复 exact hash 或相同策略签名 | `teaching_unit_not_advanced`；无第二条 message/receipt |
| compact required projection 超过 1,200 字符 | `TUTOR_TEACHING_SESSION_UNREPRESENTABLE`；provider 不调用 |
| empty shelf | `primary=null`、`secondary=[]`；Desktop 无 shelf DOM/placeholder |
| same-authority `open` / reload 遇到 completed session | 返回原 completed session，`created=false`、`pending_run=null`；不得创建新 Turn 覆盖 completion shelf |

### 5. Good / Base / Bad Cases

- Good：HTML 误区单元使用 `misconception_contrast + error_detection` 与 composer，学习者回答后下一单元改用 `learner_feedback + micro_transfer`。
- Good：Continue 改变例子或诊断策略后可提交，receipt v2 进入最近四项且不含 public message。
- Base：历史 v1 receipt 以默认空 moves/none 继续读取；legacy provider payload可解析，但不能作为 v1.1 成功 decision。
- Bad：每次 Continue 只改写同一 Lesson 段落，或由 Desktop 根据消息文本补“继续”按钮。

### 6. Tests Required

- Skill/catalog：v1.0 exact hash immutable，v1.1 manifest/instructions/evals hash、output contract 与 exact selection。
- Provider/gate：good/base/bad v2 shape、legacy parse、count/unique、composer/action/diagnostic、change-example。
- PostgreSQL/context：additive columns/default/CHECK、bootstrap twice、append-only、recent four、安全字段、消息正文缺失、serialized required projection `<=1200`。
- Loop/reducer/Desktop：重复 hash/签名拒绝、改变策略允许、composer 无 Continue、empty shelf DOM/class/placeholder 缺失、secondary-only、`refresh_session`；completed session 的 same-authority reload/open 复用原 session 且 run count 不增加。
- 完成前运行 focused serial pytest、Ruff、Mypy、lock、Desktop Vitest、三视口 fake/offline Browser、task validate 与 `git diff --check`。

### 7. Wrong vs Correct

#### Wrong

```python
context["recent_teaching_units"] = [receipt.public_message for receipt in receipts]
policy.max_required_characters += 1000
shelf.primary = local_continue_button
```

#### Correct

```python
context["recent_teaching_units"] = project_safe_recent_units(receipts[-4:])
assert len(serialize_compact(context)) <= 1200
decision_gate.reject_repeated_unit(decision, recent_units)
shelf = build_teaching_action_shelf(checkpoint_state)
```

正确路径保留既有 required-section 预算、只传安全策略元数据，并让 backend reducer 成为唯一 Action Shelf authority。
