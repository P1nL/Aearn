# 统一学习计划确认入口

## 目标

在计划制定页面建立唯一、稳定且可解释的交互职责：底部 Composer 始终用于补充目标、提出计划修改和继续对话；右侧计划草案窗口是创建正式 LearningTrack 的唯一确认入口。消除计划草案生成后出现的底部 `批准 / 拒绝` 审批卡，避免用户在两个区域之间判断“到底在哪里确认”。

## 背景与已确认事实

- `LearningPlanBuilderPage` 已在右侧计划草案窗口中通过 `confirmLearningPlanSession()` 调用正式确认接口，并携带 session version、draft id/version/content hash；该路径是当前正式计划创建入口（`aearn/apps/desktop/src/features/learning/LearningPlanBuilderPage.tsx:63-81,145-163,187-233`）。
- 后端架构明确规定 HTTP confirmation 是唯一的 track-creation action（`docs/architecture/tutor-harness-runtime.md:760-764`），正式产品流程也要求用户确认 current version/id/hash 后才原子创建 LearningTrack（`docs/product/user-flows.md:205`）。
- 当前 `TutorConversationSurface` 在任何 pending typed request 出现时都会让请求席位完全替代普通 Composer；其中 `approval` 渲染为底部 `批准 / 拒绝` 卡片（`aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx:401-420,462-505,533-543`）。
- 正式交互规格当前将 clarification、planning input 与 approval 一并定义为“完全占用 Composer 席位”（`docs/product/frontend-interaction-spec.md:116-126`）；本任务需要补充 plan-drafting 的明确例外，而不是破坏通用 typed approval 能力。
- `tutor.learning-plan-draft@1.0.1` 已说明草案生成后只需告知用户审阅，确认属于单独的 learner action（`aearn/services/api/app/agents/skills/tutor.learning-plan-draft/1.0.1/instructions.md:5-10`），但通用 provider canonical approval 示例仍直接使用“确认学习计划”文案（`aearn/services/api/app/services/tutor/decision_protocol.py:301-305`），会诱导模型创建冗余 plan approval。
- 右侧草案卡已经写明“你仍可在对话中要求调整。确认后才会创建正式学习主线”（`aearn/apps/desktop/src/features/learning/LearningPlanBuilderPage.tsx:228-232`），与本次职责划分一致。

## 需求

### R1：计划确认入口唯一化

- 在 `plan_drafting` 流程中，成功生成或更新 `current_draft` 后，不再创建用于确认该草案的 typed `approval` request。
- 创建正式 LearningTrack 只能由右侧计划草案窗口的 `确认并创建学习主线` 操作触发。
- 通用 Tutor 中真正需要显式授权的受控操作仍可使用 typed `approval`；本任务不得删除或弱化通用 approval DTO、CAS、proposal identity、approve/deny API 或非计划场景 UI。

### R2：Composer 始终承担计划沟通与修改

- 计划信息收集阶段，Composer 继续用于提交学习目标和回答普通对话输入。
- `current_draft` 已存在时，Composer 保持可见、可输入，提示语明确表达“可继续提出修改意见”，不得再被计划确认审批卡替代。
- 用户提交修改后仍通过普通 conversation input 创建 fresh finite TurnRun；新草案继续使用 append-only 新版本和服务端 current pointer，不新增前端本地计划状态。

### R3：右侧草案窗口承担审阅与确认

- 右侧窗口继续展示服务端 `current_draft` 的标题、目标、节奏、模块、知识点和来源，不伪造或本地重算计划字段。
- 确认按钮继续使用现有 session/draft/version/hash 并发与幂等契约。
- 确认进行中显示 busy/disabled；错误继续显示 learner-safe 信息并刷新服务端 session。
- 新草案版本到达后沿用现有自动展开行为；同一草案的手动收起仍应在普通刷新时保持。

### R4：模型与运行时契约纠偏

- `tutor.learning-plan-draft@1.0.1` 必须明确：草案 capability 成功后输出可见总结并结束当前 turn，不得使用 `continuation_kind=approval` 请求确认学习计划。
- 通用 provider approval 示例必须改成与学习计划无关的真正受控授权示例，避免与独立计划确认 API 冲突。
- 增加回归覆盖，证明 plan-drafting Skill/决策上下文不会再把计划确认表达为 typed approval；通用 approval 解析和响应能力保持原样。

### R5：正式规格同步

- 更新 `docs/product/frontend-interaction-spec.md` 和 `docs/product/user-flows.md`：通用 pending typed request 仍接管 Composer，但“确认当前学习计划草案”由右侧 inspector + learning-plan session confirm endpoint 独占，草案生成后的 Composer 用于继续修改。
- 如运行时说明需要同步，更新 `docs/architecture/tutor-harness-runtime.md`，明确 plan confirmation 与 generic approval 的边界。

### R6：同 Turn 请求的单次可见渲染

- 服务端可以继续为同一 Turn 原子持久化正式 Tutor `message` 与配套 `elicitation/approval` 记录；Desktop 不删除或改写权威快照。
- 当同一 Turn 同时存在正式 Tutor message 与 request 记录时，主时间线只渲染正式 message；pending request 的交互控件只在底部 typed request 席位出现一次。
- 当 legacy/request-only 快照缺少正式 Tutor message 时，保留 `TutorRequestHistory` 回退渲染，避免旧数据不可读。
- 分页 prepend 与普通 snapshot replace 必须使用同一折叠规则，不能因跨页合并再次出现重复内容。

### R7：Think 验证屏障、首段稳定与恢复不闪退

- `turn_output append` 只表示通过累计安全检查的 provisional 候选文本；无论已等待多久，在同 generation 收到 validated `complete` 前都不得进入 DOM。
- `complete` 只能由 Provider gateway 在完整 object 通过 schema/domain validation、公开文本安全检查和 stream/final exact match 后发出；repair/rejected attempt 必须 `append -> discard`，不得先 `complete`。
- 首个 live chunk 同时进入 `350ms` 内存稳定窗口；展示必须同时满足 validated `complete` 与窗口结束。窗口内或窗口后收到 authoritative `reset/discard` 时，未完成 generation 的前缀不得闪现。
- 解禁后沿用 `18ms/grapheme`、默认展开、literal/pre-wrap 和 reduced-motion 契约；snapshot 只有 `active_thinking.complete=true` 时可直接恢复文本，incomplete snapshot 保持静态 Think。
- SSE gap、generation/sequence mismatch 或 cursor recovery 触发 snapshot 时，不得先清空已经 validated 且可见的文本；由 replacement snapshot 明确保留、替换或清除。
- 同 Turn/Revision 的旧 generation snapshot 不得覆盖较新的 live generation；authoritative reset/discard、terminal error、Interrupt、Retry、repair 或 supersede 仍可清除废弃文本。

### R8：兼容与范围控制

- 不修改 `POST /api/learning-plan-sessions/{id}/confirm` 的业务语义、请求字段、幂等键或 stale 校验。
- 不修改计划草案数据结构、生成 capability、LearningTrack 创建事务或通用 typed request public contract。
- 不通过 prompt 文案或前端字符串猜测 approval 是否属于计划；应从 `plan_drafting` Skill/正式流程边界阻止新冗余 approval。
- 本任务不为开发期已经持久化的历史冗余 plan approval 做数据库迁移；新会话与新草案必须遵循新契约。若现有本地测试 session 仍停在旧 pending approval，可取消并重新创建 planning session 验证。

## 范围外

- 重设计右侧计划窗口的整体视觉、尺寸、浮动方式或响应式布局。
- 新增计划版本对比、差异高亮、快捷修改 chips 或正式计划编辑器。
- 删除通用 Tutor approval 能力或改变非计划受控操作的审批流程。
- 修改 LearningTrack、计划 revision、课程执行或 Review 流程。
- 数据库迁移或生产数据修复。

## 验收标准

- [x] 计划草案生成完成后，底部仍显示普通 Composer，不出现用于确认该草案的 `批准 / 拒绝` 卡片。
- [x] `current_draft` 存在时，Composer 的可访问标签或 placeholder 明确支持“提出修改意见”，并可发送普通 planning conversation input。
- [x] 右侧计划窗口是页面中唯一可创建正式 LearningTrack 的位置，按钮调用现有 `confirmLearningPlanSession()`。
- [x] 点击右侧确认仍携带 exact session version、draft id、draft version 与 content hash；busy、错误刷新和成功导航行为不回归。
- [x] 用户从 Composer 提出修改后，服务端可以生成更高版本的 append-only draft，右侧窗口自动显示最新版本，旧版本不能被确认。
- [x] plan-drafting Skill 明确禁止使用 typed approval 确认计划，通用 canonical approval 示例不再使用学习计划场景。
- [x] 通用 typed clarification、planning input 与非计划 approval 的组件/API 测试继续通过。
- [x] 同一 Turn 的正式 Tutor message 与 request 记录在主时间线只显示一次，底部请求席仍可响应；request-only 旧快照仍可读。
- [x] provisional append 即使持续超过 `350ms` 也不进入 DOM；只有 validated complete + 稳定窗口同时满足才显示，慢速 rejected/discard generation 不闪现，recovery snapshot 返回前已显示文本不消失。
- [x] 正式产品与架构文档明确记录“Composer 修改、右侧确认”的职责分工。
- [x] Desktop Vitest、`pnpm --dir .\aearn desktop:check` 以及相关后端定向测试通过。

## 风险与缓解

- **模型仍可能输出旧 approval 行为**：同时修改 Skill 的明确禁令与通用 canonical example，并用 fake-provider/决策契约测试锁定。
- **误伤通用 approval**：所有限制仅针对“学习计划草案确认”语义；不删除 union、API 或普通 Tutor UI。
- **文档与实现再次漂移**：同一变更同步正式 product flow、frontend interaction spec 和必要的 runtime 说明。
- **把 transport EOF 误当业务完成**：由 gateway 独占 validated `complete` 发出权；projector 只负责解析闭合与 flush，并用慢速 rejected attempt 回归锁定 `append -> discard`。
- **开发期旧 session 仍有 pending approval**：明确不做数据迁移，验收使用新 session；不在页面加载时自动批准、拒绝或修改历史请求。
