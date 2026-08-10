# Tutor 上下文治理与自适应预算

## 目标

在现有长期 `TutorConversation` 与每条普通消息独立有限 `TurnRun` 的基础上，建立一套可验证的 Tutor 上下文治理体系：每次交互都准确携带权威当前输入，按任务复杂度自适应利用模型上下文容量，将缓存 token 纳入物理窗口核算，通过“近期原文 + 增量结构化摘要 + 相关性选择”支持长对话，并以安全 usage、回归 eval 和真实 provider smoke 持续校准预算。

本任务树只治理模型上下文、provider usage、摘要压缩和评估，不重新设计已经完成的 TurnRun 生命周期、公开历史、Desktop 会话导航或 provider/model fallback 策略。

## 已确认事实

1. 已归档任务 `08-02-deepseek-responses-decision-contract` 完成了精确 `deepseek-v4-flash` Responses 适配、严格 `TutorDecision` JSON、同 provider 最多一次 repair 和安全诊断。
2. 已归档任务 `08-02-tutor-conversation-turnrun-history` 完成了长期 conversation、每条普通消息新建有限 TurnRun、旧前台 run supersede、原子首轮和公开历史。
3. 当前 `PostgresTutorContextLoader` 读取最新八条消息后反转为时间顺序，而 `TutorContextBuilder` 只选择 `RECENT_MESSAGES` 的前四项，可能让较旧消息挤掉最新输入。
4. 当前 provider payload 只有 `input_revision`、`context` 和 `context_metadata`，没有独立必需的 `current_input`。
5. 当前精确 `deepseek-v4-flash` 配置将 `1_000_000 - 384_000 = 616_000` 直接作为 context selection budget；这代表物理输入容量，不等于所有普通请求都应使用的固定产品目标。
6. provider 缓存读取 token 仍属于模型可见输入并占用物理上下文；缓存只改变计费与计算复用，不改变总输入长度。
7. `LLMJsonResponse` 当前不携带 input/cached/output/total usage，因此 Aearn 无法用真实 provider receipt 校准估算和预算策略。
8. 仓库已有 `WORKING_SUMMARY`、compaction request、curation outbox 和 `tutor_context_summaries` 基础，但交互式 loader 尚未形成“近期原文 + 有效摘要”的闭环，现有 summary 还是最多 280 字符的文本投影。

## 压缩方式

长对话压缩采用分层、增量、可回溯的方式：

1. 永远保留 system/protocol contract 与权威 `current_input`；它们不参与可选上下文竞争。
2. 使用近期原文窗口保存最新若干条既往消息；选择时从新到旧，提供给模型时按时间正序。
3. 只把移出近期窗口的消息与上一版有效摘要合并为新的结构化摘要，不反复总结仍在近期窗口中的原文。
4. 结构化摘要至少记录当前目标、已确认事实、已完成步骤、已拒绝路径、未解决问题、学习者偏好和稳定覆盖边界。
5. 计划、复习、记忆、活动、摘要和 capability schema 按当前输入的相关性与治理优先级选取，不进行完整重放。
6. 固定冲突优先级为 `current_input > recent_messages > working_summary > learner_memory/activity`；摘要不得覆盖最新纠正。
7. 摘要生成失败不得删除原始消息、阻塞 conversation 持久化或导致当前输入丢失；系统应以较少可选上下文继续或安全失败。
8. 完整原始对话继续只存于权威数据库；压缩只改变每次 provider 请求的上下文投影。

## 子任务与执行顺序

1. `08-04-tutor-latest-input-teaching-relevance`：修复权威当前输入、最新历史选择和教学纠正策略；这是首个实施子任务。
2. `08-04-tutor-provider-usage-cache-accounting`：采集并安全持久化 provider attempt usage 与缓存明细；依赖子任务 1 的 provider/context contract 稳定。
3. `08-04-tutor-adaptive-context-budget-planner`：基于完整请求估算、物理硬上限和任务复杂度规划动态预算；依赖子任务 1 和 2。
4. `08-04-tutor-context-summary-retrieval-compaction`：接通结构化摘要、近期窗口、增量压缩和有效摘要检索；依赖子任务 1 和 3，并复用子任务 2 的计量能力。
5. `08-04-tutor-context-budget-evals-observability`：完成跨层确定性 eval、安全指标和可选真实 provider smoke；依赖前四个子任务。

父任务只维护跨子任务需求、依赖、集成验收和文档一致性，不作为直接业务代码实施目标。

## 需求

### P1 — 当前输入优先

- 每个交互式 TurnRun 必须通过 `run_id + input_revision` 的持久化证据解析唯一当前学习者输入。
- 当前输入在 provider payload 中独立呈现，且任何可选历史、摘要、计划、记忆、活动或 schema 都不能挤掉它。
- 主动式 run 保持独立无输入策略，不得虚构 learner message。

### P2 — 物理硬上限与自适应目标分离

- provider 物理输入上限必须覆盖缓存输入、非缓存输入、system/protocol、JSON 外壳、动态上下文和安全余量。
- 缓存读取 token 必须计入物理总输入，但不得被错误重复加到已经包含它的 `input_tokens` 上。
- 产品动态上下文目标必须可按任务复杂度扩缩；不得把 32K、64K 或 616K 作为所有请求不可变化的单一上限。
- 请求前不能假设缓存一定命中；硬边界按完整序列化输入的保守估算执行。

### P3 — 长对话分层压缩

- 使用权威当前输入、最新既往原文、结构化 working summary 和相关可选事实构造上下文。
- 摘要只覆盖被近期窗口淘汰的历史，保留稳定覆盖游标、source identity/hash 和 schema version。
- 摘要持久化、检索、失效、重放和删除必须遵守 user/conversation scope 与现有本地用户数据边界。

### P4 — Usage 与可观测性

- 统一归一化 provider 实际 input、cached input、uncached input、output、total 和可用 reasoning token 明细。
- 每个实际 provider attempt 可独立审计，不能用 `model_call_count` 模糊替代 HTTP attempt 数。
- 只持久化安全数值、枚举、标识和 hash；不得保存 raw prompt、raw history、provider body、reasoning 或凭据。

### P5 — 确定性和安全

- 上下文选择、预算档位、驱逐顺序、摘要覆盖和冲突解析必须确定、可测试、可重放。
- 接近物理上限时先删除或压缩低优先级可选上下文；无法容纳必要 contract 与当前输入时，在 provider 调用前安全失败。
- 保持 primary-provider-only、strict JSON、安全检查、latest-input-wins、lease/CAS、公开 API/SSE 和 proactive default-deny 边界。

### P6 — 文档与规格

- 各子任务完成后更新 `docs/architecture/tutor-harness-runtime.md`、必要的数据库/API/QA source of truth 和 `.trellis/spec/backend/quality-guidelines.md`。
- 不创建重复的产品规格，不恢复已归档 Graph/onboarding runtime。

## 验收标准

- [ ] 当前输入在任何有效预算和长对话下都不会被可选上下文挤出。
- [ ] 历史选择保留最新消息并按时间正序呈现，当前输入不会在历史中重复。
- [ ] 缓存读取计入物理总输入，usage 归一化不会双重计数。
- [ ] 简单任务使用紧凑上下文，复杂任务能按证据扩展到更大档位，同时永不突破物理硬边界。
- [ ] 对话超出近期窗口后，结构化摘要保留目标、完成项、拒绝路径和未解决问题，且最新纠正优先。
- [ ] 摘要失败或 stale 时不会删除原始消息、泄露内容或调用 provider 回答缺少当前输入的请求。
- [ ] 确定性 fixtures 覆盖最新输入、预算扩缩、缓存计量、摘要冲突、硬上限和 provider-not-called 失败。
- [ ] 可选真实 provider smoke 只记录 learner-safe 输出和数值 rubric，不记录 secret、prompt、reasoning 或原始 provider payload。
- [ ] 所有子任务分别通过其聚焦测试、完整相关 API 测试、Ruff、Mypy、Trellis validate 和 `git diff --check`。

## 范围外

- 改变普通 conversation 的“一条消息一个 TurnRun”生命周期。
- 增加 provider/model/protocol fallback 或自动切换模型。
- 把完整原始会话、prompt、reasoning 或 provider body 作为摘要、trace 或公开指标保存。
- 为预算或摘要增加面向学习者的调试 UI、计费账单系统或定价抓取。
- 将真实 provider smoke 设为默认离线 CI 的强制项。
- 提交、推送、部署或修改生产数据。

## 关键决策

- 1M 级上下文是可按需使用的容量，不是每轮必须填满的目标。
- 缓存 token 计入物理窗口；动态业务预算与缓存计费明细分开治理。
- 压缩采用“近期原文 + 增量结构化摘要 + 相关性选择”，不采用全量模糊摘要或简单删除旧消息。
- 先完成当前输入正确性，再实施 usage、预算、摘要和综合评估。
