# Tutor 对话式学习工件平台技术设计

## 1. Architecture Boundary

~~~text
Learning Item Bank / ExerciseVersion / Lesson / Review authority
                         |
                         v
Teaching candidate builder -> Tutor decision v3 -> deterministic gate
                         |                 |
                         | rejected        | accepted atomically
                         v                 v
                  safe repair       message + artifact + checkpoint
                                          |
                                          v
Conversation snapshot v4 / item_added,item_updated SSE
                                          |
                                          v
Desktop inline artifact renderer + safe Markdown
                                          |
              user artifact action -------+
                         |
                         v
Gate / Review / Artifact Attempt / Runner authority
                         |
                         v
terminal result -> Tutor evaluation Turn + result artifact -> continuation
~~~

Artifact 不替代 Learning domain。Tutor 只拥有选择、对话投影、答疑 branch 和后续 Turn 调度；Gate/Review/Attempt/Runner/Item publication 各自保持 authority。

## 2. Public Contract

建议发布 `tutor_learning_artifact_v1`：

~~~ts
interface TutorLearningArtifactV1 {
  kind: "artifact";
  id: string;
  conversation_id: string;
  turn_id: string | null;
  teaching_session_id: string;
  checkpoint_id: string | null;
  artifact_version: 1;
  artifact_kind:
    | "exercise_workspace"
    | "browser_preview"
    | "test_result"
    | "knowledge_check"
    | "model_code_review"
    | "sql_workspace"
    | "demonstration"
    | "source_inspector";
  purpose:
    | "exercise"
    | "demonstration"
    | "knowledge_check"
    | "remediation"
    | "transfer_check"
    | "code_review"
    | "sql_exploration"
    | "result";
  owner_kind: "lesson_gate" | "review_item" | "teaching_practice" | "learning_item";
  owner_id: string;
  owner_version: number;
  state: "pending" | "ready" | "active" | "running" | "completed" | "failed" | "cancelled" | "superseded";
  title: string;
  instruction_markdown: string;
  difficulty: "D1" | "D2" | "D3" | "D4" | "D5" | null;
  presentation: ArtifactPresentationV1;
  allowed_actions: ArtifactActionKind[];
  source_references: SafeArtifactReferenceV1[];
  active_attempt: SafeAttemptSummaryV1 | null;
  branch_summary: SafeBranchSummaryV1 | null;
  version: number;
  created_at: string;
  updated_at: string;
  terminal_at: string | null;
}
~~~

Presentation 与 action 都是封闭 union。大型详情可通过 scoped artifact endpoint 读取，snapshot 可投影 bounded summary + active detail；SSE 只发送 item reference。

## 3. Persistence

建议新增 schema fragment（实际编号由 manifest 当前末尾决定，不能按目录自然顺序猜测）并包含：

- `tutor_learning_artifacts`：当前 artifact authority、owner、presentation hash、state/version。
- `tutor_learning_artifact_events`：append-only lifecycle/audit。
- `tutor_learning_artifact_references`：稳定 source refs。
- `tutor_learning_artifact_attempt_links`：Artifact 到已有 Attempt/Execution 的关联。
- `tutor_conversation_branches`：anchor、kind、state、checkpoint、depth=1。
- `tutor_conversation_branch_items`：branch 与 message/item 的显式有序归属。
- Learning Item Bank child 所需 shared immutable item/version/private evaluation/publication/review tables。

所有 user-owned 表必须进入 cutover exhaustive inventory、export/reset/delete；shared published item/version/rubric 必须明确列入 shared allowlist。状态 transition、append-only、scope FK、partial unique active artifact、CAS 和 one-active-turn 继续由 PostgreSQL 保护。

## 4. API

建议新增：

- `GET /api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}`
- `POST /api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/actions`
- `GET /api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/attempts/{attempt_id}`
- 题库 author/verify/review/publish 使用内部 service/worker/admin seam，不向学习者开放任意生成接口。

Action closed union：`request_hint | run | respond | complete_review | cancel | acknowledge_demo_event`。每次写入携带 user ID、client_action_id、expected artifact version 和 action-specific immutable payload。

Run endpoint 是 facade：根据 owner 委派 Gate、Review 或 teaching-practice service，不重写 scorer/mastery。成功响应返回 fresh artifact projection 与 optional Attempt；模型不能提供 endpoint 或 target URL。

## 5. Snapshot and SSE

- 发布 `tutor_conversation_snapshot_v4`，保留 v3 read compatibility。
- TutorPublicItem 与 item reference 新增 artifact；可进入支线的 public item additive 携带 optional `branch_id`，snapshot 同时投影 exact `branches[]` group summary。
- Artifact/branch 生命周期继续使用 `item_added/item_updated`；无需增加 editor/preview/test/sql 专用 SSE event。
- `turn_output` 保持当前 validated stream authority，不用于未验证 Markdown 或 Artifact args。
- 非 turn-output event 继续触发节流 snapshot refresh；gap/cursor invalid fresh snapshot。
- Attempt terminal transaction 同时更新 artifact、追加 artifact event、追加 conversation item_updated；Tutor evaluation Turn 由幂等 continuation intent 调度。

## 6. Teaching Decision v3

发布 immutable `tutor.lesson-teaching@1.2.0` 和 `tutor.teaching-step-decision.v3`：

~~~ts
interaction: {
  mode: "none" | "composer" | "artifact";
  intent:
    | "none"
    | "text_answer"
    | "structured_answer"
    | "edit_code"
    | "run_code"
    | "review_diff"
    | "execute_query"
    | "interact_with_demo";
  artifact_handle: string | null;
}
~~~

Context 只提供最多约 8 个 server-built candidate handles。edit/run/review/query/demo intent 必须精确匹配候选、current session/checkpoint/track/knowledge/assignment/runtime capability；否则整条不可执行 public message 被拒绝并走 bounded repair/fallback。

原子 commit：Tutor message + action receipt + checkpoint + artifact + conversation item/event + source turn terminal。Artifact terminal evidence 可创建最多一个后续 Tutor Turn。

## 7. Turn Arbiter and Clarification Branches

优先级：

~~~text
learner message
> explicit artifact action
> expected interactive event
> static display timer
> background continuation
~~~

计时/terminal 只创建 pending continuation intent，不直接调用模型。用户消息到达时可消费或延迟 pending intent，保证一个 conversation 同时只有一个可发布 Tutor Turn。

普通消息在 active blocking artifact 下创建/复用 depth=1 branch；control intent 不进入 branch。Branch 包含用户和 Tutor item，UI 左侧 branch rail 包裹，用户仍右对齐。主线动作后 branch resolved，默认折叠。无关问题 disposition 为 answer-and-refocus；明确切换主题需要确认 pause/cancel。

## 8. Desktop Rendering

`TutorConversationSurface` 仍是唯一 timeline、snapshot、SSE、Composer reducer。新增 inline renderer：

- message -> SafeMarkdownMessage
- artifact -> InlineArtifactMessage
- resolved branch -> CollapsedBranchSummary / expanded BranchGroup

活动 Artifact 自动展开和滚动，不抢焦点。Artifact 组件按 presentation kind 注册在静态 registry 中。完成后直到下一 learner message 保持展开；终态历史默认 lightweight summary，展开时按需加载 detail。程序内保留 Monaco/Preview/scroll/tab 状态，重开从服务器重建。

## 9. Safe Markdown

使用 AST/sanitizer pipeline：

~~~text
stream buffer -> partial Markdown parser -> closed node projection
-> custom size/color directive validator -> sanitizer -> React renderer
~~~

允许 GFM、代码、表格、引用、安全链接和受控 custom directives。raw HTML disabled。Size/颜色有 allowlist/range/contrast gate；URL scheme/host policy由 Desktop 控制。Artifact directives 不在 Markdown parser 中实现。

## 10. Browser Preview Security

视觉嵌入对话 Artifact，执行隔离于 main WebView：

- dedicated preview host/webview identity，无 Tauri permission/IPC；main capability 不匹配 preview。
- fixed host document、opaque/custom origin、non-null CSP、connect/form/navigation/object/frame/worker deny。
- source 只来自 reviewed item + local draft；显式 nonce/session/artifact bridge。
- 只上报 ready、bounded console、runtime_error、safe interaction event。
- 防抖实时 reload；timeout/hang/crash 时销毁重建；源码/日志/消息频率有界。
- Preview 标记本地非权威，Run 仍走 server Attempt。

若 Tauri 技术验证无法提供嵌入式低权限 child webview，不得退回在 main DOM 执行任意 JS；该 child 必须先形成安全 spike 结论再实现。

## 11. Execution Result v2

`SafeExecutionResultV2` 保留 v1 字段并新增 closed optional presentation：`none | table_result_v1`。测试 case 保持 hidden ordinal redaction。SQL table bounds：列、行、cell 和 payload 均有硬限制，公开数据与隐藏评分数据集分离。

Run terminal 流程：

~~~text
Attempt terminal
-> artifact owner decision
-> artifact updated/completed
-> new Tutor Turn
   -> Markdown evaluation (model or deterministic fallback)
   -> immutable test-result artifact (server-authored)
~~~

评价模型只收到 safe result；result artifact 不由模型生成。模型失败不能丢失权威结果。

## 12. Demonstration Design

- `demonstration_mode=interactive|static`。
- 代码视图只读；interactive host 只允许 descriptor 声明的 event。
- Static duration：课程 6-30s 配置优先；否则按 CJK/word/code-line/animation 估算并 clamp，过长内容应拆分。
- Visible-time clock 在 foreground、current conversation、artifact visible、render ready 时运行；暂停时 progress animation 同步暂停。
- completion receipt 不进入 mastery；completion intent 低于 learner message。

## 13. Knowledge, Hint, Review, SQL and Sources

- Knowledge answer immutable，outcome 与 artifact completion 分离；补救 successor 关联 predecessor。
- Difficulty profile 保存 reasoning depth、concept count、context novelty、transfer、response complexity、scaffolding；UI 只显示 base D(n)。
- Hint popover 使用 portal/overlay，不参与布局；scroll-snap 横向页按 first-view receipt 解锁。
- Model Review v2 使用 immutable source/diff hash、hunk/line map、structured finding；v1 history compatible。
- SQL workspace 原工件显示 public result grid，Tutor result item显示 tests；只读 query grammar/policy fail closed。
- Source reference exact document/version/block/hash；drawer 定位与 highlight 只使用 server identity，不按文本猜测。

## 14. Learning Item Bank and Review Pipeline

Item 包含 public content、private evaluation、difficulty、knowledge/prerequisite、purpose、runtime、hints、remediation、sources、status/hash/version。创建流程：

~~~text
blueprint -> draft -> schema/markdown/runtime/scorer verification
-> blind role reviews -> adjudication -> pilot -> publish/retire
~~~

审核角色：curriculum、difficulty、technical、ambiguity、security、adversarial；生成者不可审核自己。任何 deterministic/security/uniqueness blocker 拒绝，多数票不能覆盖。低风险可 agent-reviewed pilot 后自动发布，中风险需真实 fixture telemetry，高风险人工最终批准。

Online Tutor 只看到 safe handle/kind/purpose/difficulty/allowed interaction，不看答案、rubric、tests 或完整源码。

## 15. Compatibility and Migration

- 新 Skill 和 contracts 发布新版本，不改写 1.1.0/v1。
- Snapshot v4 读 v3 history；旧客户端在 feature disabled 时保持现有消息流。
- Existing Gate/Review APIs 可继续服务旧 Lesson UI；Artifact API 作为新 facade 渐进切入。
- 新 schema additive、bootstrap repeatable；历史 rows 不 backfill invented Artifact。
- Protected design prototype 保留。

## 16. Feature Flags and Rollback

建议能力门：

- `TUTOR_LEARNING_ARTIFACTS_ENABLED`
- `TUTOR_ARTIFACT_TEACHING_MODE_ENABLED`
- `DESKTOP_INLINE_ARTIFACTS_ENABLED`
- `DESKTOP_BROWSER_PREVIEW_ENABLED`
- `LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED`

关闭后 candidate builder 不提供 artifact handle，decision gate 不允许 artifact intent；已有 rows 保留只读可恢复。Preview 可单独关闭，不能伪装成 A3a。回滚代码不删除 Artifact/Attempt/Item history。

## 17. Child Ownership and Dependencies

- Child 01 是 DB/public contract/API 基础，先于所有其他实现。
- Child 11 可与 01 并行设计，但 online candidate 接入依赖 01/02。
- Child 02、03 依赖 01；04/05/06/07/08/09/10 依赖 03 的 shell，相关 authority 依赖 01/02/11。
- Child 04 依赖 05 的 result contract；Child 09 依赖 05 table result。
- Child 12 等待所有功能 child 完成，拥有 cross-child docs/QA/rollout，不重复各 child 实现。
