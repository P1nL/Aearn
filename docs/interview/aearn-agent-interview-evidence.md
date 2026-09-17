# Aearn Agent 面试证据索引

**核对日期：2026-09-16；源码基线：`4b595e0507282c01d8f36840990671cfcf3420a3`。**

[返回导航](README.md) · [阅读完整问答](aearn-agent-design-handbook.md)

## 如何理解证据

| 维度 | 标签与含义 | 不代表什么 |
| --- | --- | --- |
| 实现 | 当前实现、部分实现、历史方案、规划/建议 | 文件存在不等于接入主链或默认开启 |
| 源码核对 | 已读取相关代码、配置、测试断言并定位 | 不等于本轮执行测试或真实运行 |
| 自动化测试 | 明确命令、日期、环境和用例范围的通过记录 | fixture 不能证明真实模型输出或长期学习效果 |
| 真实运行 | 指定配置、数据和链路的实际回执 | 不自动推广到其他语言、题型、并发和生产环境 |
| 发布 | 另行授权与完整发布条件 | 文档、构建或单次成功不是发布批准 |

本索引按题记录结论、源码、测试入口与限制。符号和行号帮助复核，但代码变更后需重新核对。相关测试文件的链接只是定位，不隐含本轮执行通过。

## 已发现的实现与说明差异

| 项目 | 本轮应采用的说法 | 详见 |
| --- | --- | --- |
| 教学 Skill 版本 | 当前权威检查是 1.2.1 / decision v3；旧索引和部分规范还保留 1.2.0、1.1.0 或旧协议描述。手册按源码解释，未顺手更改旧规格 | [AG-08-002](aearn-agent-design-handbook.md#ag-08-002)、[AG-08-003](aearn-agent-design-handbook.md#ag-08-003) |
| 大上下文与实际装配 | 模型窗口不等于每次输入；builder 还有来源字符和历史数量限制，不能宣称所有相关文本都完整装入 | [AG-05-002](aearn-agent-design-handbook.md#ag-05-002)、[AG-05-004](aearn-agent-design-handbook.md#ag-05-004) |
| 必需上下文的保真边界 | 通用清洗器会裁剪嵌套列表和映射，集合项减少不一定触发拒绝或截断计数；不能把 required 标签解释成任意对象无损保留 | [AG-05-002](aearn-agent-design-handbook.md#ag-05-002)、[AG-06-002](aearn-agent-design-handbook.md#ag-06-002) |
| 自动摘要与推断记忆 | 摘要、推断记忆和课程状态是不同通路；后台预算与启用状态要分别检查，读路径不能泛称自动 TTL 过滤 | [AG-05-006](aearn-agent-design-handbook.md#ag-05-006)、[AG-06-002](aearn-agent-design-handbook.md#ag-06-002) |
| RAG 接线 | 课程生成的持久化 grounding，与当前交互式 Tutor 的 capability/lookup 接线不是同一结论；RAG 2.0 新任务仍是规划 | [第 07 章](aearn-agent-design-handbook.md#topic-07) |
| 容器执行 | 有固定隔离启动配置，但 reviewed image-lock 清单为空且默认关闭，不是当前生产可用证明 | [AG-12-002](aearn-agent-design-handbook.md#ag-12-002) |
| 可见 Runtime 输出 | 前端协议允许 reasoning/final_answer 项；不能写成所有 reasoning 永不展示，也不能因此允许任意内部载荷公开 | [AG-12-003](aearn-agent-design-handbook.md#ag-12-003)、[AG-13-001](aearn-agent-design-handbook.md#ag-13-001) |

<a id="rag-planning-snapshot"></a>

## RAG 本地规划状态快照

以下为 2026-09-16 从本地 Trellis 任务元数据核对的状态，**不是源码提交 `4b595e0` 内的文件，也不是功能未实现的单一判据**。活动任务目录被 Git 忽略，因此正式手册保存这个最小状态快照，不要求读者打开本机未版本化的路径。已有 grounding 能力仍以第 07 章所引源码为准。

| 本地任务目录标识 | 当日状态 |
| --- | --- |
| `09-03-rag-bounded-hybrid-retrieval-coverage` | `planning` |
| `09-03-rag-language-ecosystem-adaptive-retrieval` | `planning` |
| `09-03-rag-operator-corpus-cli` | `planning` |
| `09-03-rag-plan-preflight-migration-proposals` | `planning` |
| `09-03-rag-shadow-integration-fixtures-docs` | `planning` |
| `09-03-rag-subject-capability-taxonomy` | `planning` |
| `09-03-rag-versioned-corpus-authority` | `planning` |

## 本次工作已有的验证记录

以下是 2026-09-16 **前置工作树提交阶段**的实际执行记录，不是正文写作时重新进行的全量验收：

- `pnpm desktop:check`：TypeScript 与 Vite 构建通过。
- 7 个相关前端测试文件，共 133 个测试通过：LearningWorkspaceProgressRefresh、ReviewSessionKnowledgePrompt、TrackLearningWorkspace、ClarificationBranchGroup、planCatalogMapping、tutorInputTeachingScope、tutorApiV2。
- 3 个离线后端测试文件，共 54 个测试通过：test_tutor_context_budget、test_codex_runtime_config、test_planning_runtime_limits；配置不可达的本地数据库地址，并排除 real_provider 测试标记。
- 92 个变更 Python 文件完成 AST 解析，暂存区 diff 空白检查通过。
- 当时扫描未发现新增高置信度凭据；这不是完整安全审计。352 个本地 output 记录保持在本地，未复制到本手册。

正文写作阶段完成源码、测试断言、官方资料与文档结构检查。独立检查额外执行 API 的 Ruff 静态检查（禁用缓存）与 Mypy（258 个源文件，禁用增量缓存），均通过；另运行两例无网络、无数据库的纯函数合成输入，复核通用上下文清洗器的既有集合裁剪：13 项列表变成 12 项、21 字段映射变成 20 字段，未拒绝且 truncated_count 为 0。该结果只证明这个组件边界，不证明真实会话已丢失事实，也不是 provider、数据库或完整 pytest 验收。

本轮未新增真实 provider、数据库、浏览器业务验收、Docker conformance 或压测。三张 Mermaid 图经过静态结构和职责审查，未进行可视化渲染，不能作为真实运行截图。

## 逐题证据

### AG-01-001

[对应问题：为什么 Aearn 需要 Agent，而不是在聊天框后面接一个大模型？](aearn-agent-design-handbook.md#ag-01-001)

- **核心结论**：Tutor Harness 通过有界决策循环组织模型、权限校验与领域操作；受控 Sidecar 的新准入限于符合条件的规划作用域，服务分层不等于多 Agent 协商。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[tutor-harness-runtime.md:28](../architecture/tutor-harness-runtime.md#L28)；[run_loop.py:60](../../aearn/services/api/app/services/tutor/run_loop.py#L60)（`TutorRunLoop`）。
- **相关测试**：[test_tutor_evals.py:34](../../aearn/services/api/tests/tutor/test_tutor_evals.py#L34)（`test_fake_only_tutor_eval_fixture_covers_pinned_catalog_and_required_scenarios`）。
- **边界**：不能声称所有路径都由 Codex 或多 Agent 驱动，也不能把接入模型本身当作 Agent 工程成果。

### AG-01-002

[对应问题：你怎样定义这个学习 Agent 的成功，而不只看回答是否流畅？](aearn-agent-design-handbook.md#ag-01-002)

- **核心结论**：教学会话、Gate/Attempt 和进度由服务端领域逻辑维护；所引 Gate fixture 检查正式提交后的 progress_changed，不提供长期学习收益证据。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[README.md:8](../README.md#L8)；[teaching_sessions.py:1599](../../aearn/services/api/app/services/learning/teaching_sessions.py#L1599)（`TeachingSessionService`）；[acceptance-test-plan.md:1](../qa/acceptance-test-plan.md#L1)。
- **相关测试**：[test_tutor_adaptive_teaching_evals.py:34](../../aearn/services/api/tests/tutor/test_tutor_adaptive_teaching_evals.py#L34)（`test_gate_completion_admits_exactly_one_progress_turn_and_frozen_summary`）。
- **边界**：不把 202 受理、模型文案、局部测试或单个课程结果写成完整教学效果与发布证明。

### AG-01-003

[对应问题：面试时怎样介绍个人工作与项目难点，才能经得起追问？](aearn-agent-design-handbook.md#ag-01-003)

- **核心结论**：所举上下文组装与决策校验模块有源码入口；个人职责、历史动机与收益不能由仓库存在这些模块推断。
- **实现状态**：规划/建议（讲述方法；个人职责待本人确认）
- **验证状态**：源码入口核对；个人分工与收益未验证，讲述方法不适用产品单测；核对日期 2026-09-16。
- **源码/规格**：[README.md:79](../README.md#L79)；[context_builder.py:118](../../aearn/services/api/app/agents/harness/context_builder.py#L118)（`TutorContextBuilder`）；[decision_gate.py:40](../../aearn/services/api/app/services/tutor/decision_gate.py#L40)（`CatalogTutorDecisionGate`）。
- **相关测试**：无专属自动化测试记录；不把方案分析当实测。
- **边界**：本文提供项目事实与讲述模板，不证明读者的个人贡献、团队规模、上线状态或商业收益。

### AG-02-001

[对应问题：从用户发出一条消息，到页面出现教学结果，完整链路是什么？](aearn-agent-design-handbook.md#ag-02-001)

- **核心结论**：桌面发送带用户、会话和幂等身份的输入；API 受理时选择或复用服务端冻结的 Runtime，再持久化输入和待处理工作。对应 Worker 按 Runtime 类型领取任务，执行模型与领域操作；桌面通过 SSE 或快照读取公开投影。受理、执行、业务完成和显示完成是不同阶段。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[tutor.py:228](../../aearn/services/api/app/routes/tutor.py#L228)（`create_conversation_input`）；[public_api.py:216](../../aearn/services/api/app/services/tutor/public_api.py#L216)（`TutorPublicService.accept_conversation_input`）；[public_api.py:907](../../aearn/services/api/app/services/tutor/public_api.py#L907)（`TutorPublicService._accept_conversation_input`）；[runtime_selection.py:171](../../aearn/services/api/app/services/tutor/runtime_selection.py#L171)（`TutorRuntimeSelectionPolicy.select`）；[interactive_worker.py:67](../../aearn/services/api/app/services/tutor/interactive_worker.py#L67)（`TutorInteractiveWorker.dispatch_job`）；[useTutorConversationStream.ts:137](../../aearn/apps/desktop/src/hooks/useTutorConversationStream.ts#L137)。
- **相关测试**：[test_tutor_conversation_runtime.py:117](../../aearn/services/api/tests/tutor/test_tutor_conversation_runtime.py#L117)（`test_fresh_v2_turn_job_and_events_roll_back_together`）。
- **边界**：这条链路解释当前架构，不表示每一种 Runtime、语言与教学场景都已真实验收。

### AG-02-002

[对应问题：为什么已经用了 Celery，还要在 PostgreSQL 里保留任务和状态？](aearn-agent-design-handbook.md#ag-02-002)

- **核心结论**：Celery 在这里主要负责唤醒和周期调度，数据库决定谁的工作处于什么状态、谁持有当前执行权，以及哪些结果已经提交。队列投递可能重复或错过唤醒，不能把一次消息消费当成一次业务完成。持久化任务让重试、恢复和核对有共同依据。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[tutor-harness-runtime.md:34](../architecture/tutor-harness-runtime.md#L34)；[interactive_worker.py:67](../../aearn/services/api/app/services/tutor/interactive_worker.py#L67)（`TutorInteractiveWorker.dispatch_job`）；[interactive_worker.py:177](../../aearn/services/api/app/services/tutor/interactive_worker.py#L177)（`TutorInteractiveWorker.reconcile`）；[interactive_worker.py:209](../../aearn/services/api/app/services/tutor/interactive_worker.py#L209)（`enqueue_tutor_interactive_dispatch`）；[worker_app.py:20](../../aearn/services/worker/aearn_worker/worker_app.py#L20)（`celery_app.conf.beat_schedule`）。
- **相关测试**：[test_tutor_conversation_runtime.py:251](../../aearn/services/api/tests/tutor/test_tutor_conversation_runtime.py#L251)（`test_dispatch_job_lease_retry_dead_and_snapshot_error_projection`）。
- **边界**：不把 Celery delivery、租约或单个事务夸大为端到端 exactly-once 模型执行。

### AG-02-003

[对应问题：用户、会话和课程的隔离在哪里做？能直接称为生产级多租户系统吗？](aearn-agent-design-handbook.md#ag-02-003)

- **核心结论**：当前公开服务会规范化用户和会话标识，并通过 repository 按学习者作用域读取状态；入口还受 cutover 决定约束。这能说明业务对象不是随意跨用户读取，但不能仅凭一个 user_id 参数就宣称已完成公网身份认证、租户 IAM 或生产安全审计。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[public_api.py:482](../../aearn/services/api/app/services/tutor/public_api.py#L482)（`TutorPublicService.read_conversation_snapshot`）；[public_api.py:516](../../aearn/services/api/app/services/tutor/public_api.py#L516)（`TutorPublicService.replay_conversation_events`）；[cutover.py:256](../../aearn/services/api/app/services/tutor/cutover.py#L256)（`HarnessCutoverService`）；[tutor-harness-runtime.md:10](../architecture/tutor-harness-runtime.md#L10)。
- **相关测试**：[test_tutor_run_repository.py:86](../../aearn/services/api/tests/tutor/test_tutor_run_repository.py#L86)（`test_input_acceptance_checks_user_scope_and_persists_exact_catalog_selection`）。
- **边界**：这不是完整安全审计；不宣称当前项目已经具备生产级多租户认证或公网部署保障。

### AG-03-001

[对应问题：Aearn 当前到底用了什么 Agent 框架，是否还是 LangGraph 或 Agents SDK？](aearn-agent-design-handbook.md#ag-03-001)

- **核心结论**：活跃产品为 Tutor Harness 加按服务端策略准入并冻结身份的 plan_drafting Codex 分支；旧 Graph/Router/SDK 不是现行产品运行时。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[pyproject.toml:6](../../aearn/services/api/pyproject.toml#L6)（`project.dependencies`）；[runtime_selection.py:171](../../aearn/services/api/app/services/tutor/runtime_selection.py#L171)（`TutorRuntimeSelectionPolicy.select`）；[run_loop.py:90](../../aearn/services/api/app/services/tutor/run_loop.py#L90)（`TutorRunLoop.run`）；[codex_dispatcher.py:176](../../aearn/services/api/app/services/tutor/codex_dispatcher.py#L176)（`CodexTutorRunDispatcher.dispatch`）。
- **相关测试**：[test_tutor_run_loop.py:799](../../aearn/services/api/tests/tutor/test_tutor_run_loop.py#L799)；[test_codex_plan_drafting_cutover.py:502](../../aearn/services/api/tests/codex_sidecar/test_codex_plan_drafting_cutover.py#L502)。
- **边界**：不能称当前主链仍由 LangGraph/Agents SDK 驱动，也不能说所有 Tutor 请求都使用 Codex。

### AG-03-002

[对应问题：为什么有了 Agent 框架，业务状态仍必须由服务端掌握？](aearn-agent-design-handbook.md#ag-03-002)

- **核心结论**：候选决策、执行状态与领域权威分离；服务器拥有授权、标识、版本 fencing 和计划确认提交。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[decision_protocol.py:766](../../aearn/services/api/app/services/tutor/decision_protocol.py#L766)（`parse_tutor_provider_items`）；[decision_gate.py:54](../../aearn/services/api/app/services/tutor/decision_gate.py#L54)（`CatalogTutorDecisionGate.validate`）；[plan_tools.py:689](../../aearn/services/api/app/services/learning/plan_tools.py#L689)（`LearningPlanToolService._fence_result`）；[plan_service.py:214](../../aearn/services/api/app/services/learning/plan_service.py#L214)（`LearningPlanSessionService._confirm_session`）。
- **相关测试**：[test_tutor_provider_gateway.py:1598](../../aearn/services/api/tests/tutor/test_tutor_provider_gateway.py#L1598)；[test_learning_plan_sessions.py:339](../../aearn/services/api/tests/learning/test_learning_plan_sessions.py#L339)。
- **边界**：不能声称采用任何框架即可自动获得 Aearn 学习状态的 exactly-once 保证；本题未完成真实数据库并发验收。

### AG-03-003

[对应问题：为什么不直接用 LangGraph？它能解决什么，又不能替项目决定什么？](aearn-agent-design-handbook.md#ag-03-003)

- **核心结论**：LangGraph 不在当前 API 直接依赖和活跃主链中；重新采用它仍须保留现有领域权威，比较仅为方案分析。
- **实现状态**：当前实现（Harness）；历史方案（旧 Graph）；规划/建议（替代比较）
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[pyproject.toml:6](../../aearn/services/api/pyproject.toml#L6)（`project.dependencies`）；[run_loop.py:524](../../aearn/services/api/app/services/tutor/run_loop.py#L524)（`TutorRunLoop._refresh_before_unsafe_boundary`）；[plan_tools.py:575](../../aearn/services/api/app/services/learning/plan_tools.py#L575)（`LearningPlanToolService.draft`）。
- **相关测试**：[test_tutor_run_loop.py:799](../../aearn/services/api/tests/tutor/test_tutor_run_loop.py#L799)；[test_tutor_run_loop.py:421](../../aearn/services/api/tests/tutor/test_tutor_run_loop.py#L421)。
- **边界**：不得说 LangGraph 没有持久化、恢复或人工介入；不得虚构删除旧 Graph 的历史动机或性能收益。

### AG-03-004

[对应问题：OpenAI Agents SDK 与自建 Harness 有什么区别，为什么不能把 SDK guardrail 当业务保证？](aearn-agent-design-handbook.md#ag-03-004)

- **核心结论**：当前 Harness 的领域检查不能由 SDK session 或 guardrail 名称替代；SDK 是可评估的运行设施而非当前主链依赖。
- **实现状态**：当前实现（Harness）；规划/建议（SDK 对比）
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[pyproject.toml:6](../../aearn/services/api/pyproject.toml#L6)（`project.dependencies`）；[decision_gate.py:54](../../aearn/services/api/app/services/tutor/decision_gate.py#L54)（`CatalogTutorDecisionGate.validate`）；[plan_tools.py:689](../../aearn/services/api/app/services/learning/plan_tools.py#L689)（`LearningPlanToolService._fence_result`）。
- **相关测试**：[test_codex_learning_plan_tools_postgres.py:75](../../aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools_postgres.py#L75)；[test_tutor_run_loop.py:421](../../aearn/services/api/tests/tutor/test_tutor_run_loop.py#L421)。
- **边界**：不得说 SDK 没有持久化或 guardrails；本项目未因此获得 SDK 所有能力，也未执行 SDK 替代方案验收。 官方护栏有作用范围：输入在链首agent、输出在最终输出agent、工具护栏在绑定的function tools执行，不能推广到每次handoff或所有工具。

### AG-03-005

[对应问题：直接调用模型 API、自建 Harness 和使用 Agent 框架，是互斥选择吗？](aearn-agent-design-handbook.md#ag-03-005)

- **核心结论**：当前自建 HTTP 客户端与 Tutor Harness 分层协作；直接模型 API 与运行时控制层不是互斥概念。
- **实现状态**：当前实现；规划/建议（替代比较）
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[llm_client.py:180](../../aearn/services/api/app/services/llm/llm_client.py#L180)（`OpenAICompatibleClient.complete_json`）；[provider_gateway.py:173](../../aearn/services/api/app/services/tutor/provider_gateway.py#L173)（`PrimaryTutorProviderGateway.decide`）；[decision_protocol.py:766](../../aearn/services/api/app/services/tutor/decision_protocol.py#L766)（`parse_tutor_provider_items`）；[run_loop.py:90](../../aearn/services/api/app/services/tutor/run_loop.py#L90)（`TutorRunLoop.run`）。
- **相关测试**：[test_tutor_provider_gateway.py:477](../../aearn/services/api/tests/tutor/test_tutor_provider_gateway.py#L477)；[test_tutor_provider_gateway.py:899](../../aearn/services/api/tests/tutor/test_tutor_provider_gateway.py#L899)。
- **边界**：不能把 OpenAI-compatible 命名写成项目依赖 Agents SDK，也不能保证所有兼容 provider 具有相同结构化输出能力。

### AG-03-006

[对应问题：Codex Sidecar 在项目中做什么，为什么不是把完整编码代理直接交给学习者？](aearn-agent-design-handbook.md#ag-03-006)

- **核心结论**：Codex 仅作为受控 plan_drafting 执行内核接入；隔离配置与服务端工具 fencing 共同保护业务边界。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[codex_config.py:135](../../aearn/services/api/app/agents/runtime/codex_config.py#L135)（`ensure_codex_runtime_home`）；[codex_adapter.py:108](../../aearn/services/api/app/agents/runtime/codex_adapter.py#L108)（`CodexAppServerRuntime.start_thread`）；[codex_dispatcher.py:176](../../aearn/services/api/app/services/tutor/codex_dispatcher.py#L176)（`CodexTutorRunDispatcher.dispatch`）；[plan_tools.py:689](../../aearn/services/api/app/services/learning/plan_tools.py#L689)（`LearningPlanToolService._fence_result`）。
- **相关测试**：[test_codex_learning_plan_tools.py:174](../../aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools.py#L174)；[test_codex_learning_plan_tools_postgres.py:75](../../aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools_postgres.py#L75)。
- **边界**：不能称已向所有学习者开放完整 Codex 编码环境；不能笼统声称所有 reasoning 都不展示，也不能称公开投影等于原始 provider 载荷。

### AG-03-007

[对应问题：Harness 与 Codex 如何选路，故障时为什么不直接互相兜底？](aearn-agent-design-handbook.md#ag-03-007)

- **核心结论**：运行时身份由服务端确定并冻结；新 Codex 准入严格校验 readiness，失败不静默切换引擎。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[runtime_selection.py:171](../../aearn/services/api/app/services/tutor/runtime_selection.py#L171)（`TutorRuntimeSelectionPolicy.select`）；[config.py:82](../../aearn/services/api/app/core/config.py#L82)（`Settings.codex_runtime_enabled`）；[codex_dispatcher.py:176](../../aearn/services/api/app/services/tutor/codex_dispatcher.py#L176)（`CodexTutorRunDispatcher.dispatch`）。
- **相关测试**：[test_codex_plan_drafting_cutover.py:1579](../../aearn/services/api/tests/codex_sidecar/test_codex_plan_drafting_cutover.py#L1579)；[test_codex_plan_drafting_cutover.py:1807](../../aearn/services/api/tests/codex_sidecar/test_codex_plan_drafting_cutover.py#L1807)。
- **边界**：不能称当前具备 Harness/Codex 无感跨引擎故障转移；不能把关闭准入等同于迁移全部历史会话。

### AG-03-008

[对应问题：怎样诚实回答“为什么从 Graph/SDK 迁移到自建”，并评估未来是否换回框架？](aearn-agent-design-handbook.md#ag-03-008)

- **核心结论**：退役与当前结构有文档、依赖和源码约束；迁移原因及未来框架收益不能由这些事实反推。
- **实现状态**：历史方案；当前实现；规划/建议（未来评估）
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[README.md:3](../README.md#L3)（`Current runtime status`）；[pyproject.toml:6](../../aearn/services/api/pyproject.toml#L6)（`project.dependencies`）；[run_loop.py:90](../../aearn/services/api/app/services/tutor/run_loop.py#L90)（`TutorRunLoop.run`）；[plan_tools.py:689](../../aearn/services/api/app/services/learning/plan_tools.py#L689)（`LearningPlanToolService._fence_result`）。
- **相关测试**：[test_tutor_run_loop.py:799](../../aearn/services/api/tests/tutor/test_tutor_run_loop.py#L799)；[test_tutor_run_loop.py:859](../../aearn/services/api/tests/tutor/test_tutor_run_loop.py#L859)。
- **边界**：不虚构迁移动机、业务收益、个人职责或替代框架对比数据；未来试验只是建议。

### AG-04-001

[对应问题：模型如何决定下一步，怎样防止自由文本直接变成业务操作？](aearn-agent-design-handbook.md#ag-04-001)

- **核心结论**：Harness 通过输入修订/租约、严格 provider items、服务端标识和 catalog gate 将模型建议收敛为有界动作。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[run_loop.py:90](../../aearn/services/api/app/services/tutor/run_loop.py#L90)（`TutorRunLoop.run`）；[decision_protocol.py:149](../../aearn/services/api/app/services/tutor/decision_protocol.py#L149)（`_StrictProviderModel`）；[decision_protocol.py:766](../../aearn/services/api/app/services/tutor/decision_protocol.py#L766)（`parse_tutor_provider_items`）；[decision_gate.py:54](../../aearn/services/api/app/services/tutor/decision_gate.py#L54)（`CatalogTutorDecisionGate.validate`）；[provider_gateway.py:67](../../aearn/services/api/app/services/tutor/provider_gateway.py#L67)（`PRIMARY_PROVIDER_DECISION_ATTEMPTS`）。
- **相关测试**：[test_tutor_provider_gateway.py:1404](../../aearn/services/api/tests/tutor/test_tutor_provider_gateway.py#L1404)；[test_tutor_run_loop.py:502](../../aearn/services/api/tests/tutor/test_tutor_run_loop.py#L502)。
- **边界**：不能把每次合法结构化输出称为安全业务成功；不能声称只有模型 prompt 在控制工具权限。

### AG-04-002

[对应问题：学习者只说“想做后端”时，如何确定语言，又为什么不能让模型直接确认 Python？](aearn-agent-design-handbook.md#ag-04-002)

- **核心结论**：语言解析受当前目录与确定性规则约束，语义shortlist仍需确认；Codex先读上下文，再接受一个四选一direction_action，可修复错误可预算内重提，已接受后的重复/冲突动作拒绝。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[planning_intent.py:140](../../aearn/services/api/app/services/learning/planning_intent.py#L140)（`PlanningIntentResolver.resolve`）；[planning_intent.py:239](../../aearn/services/api/app/services/learning/planning_intent.py#L239)（`PlanningIntentResolver.resolve_for_run`）；[planning_intent.py:291](../../aearn/services/api/app/services/learning/planning_intent.py#L291)（`PlanningIntentResolver.language_candidates`）；[planning_intent.py:401](../../aearn/services/api/app/services/learning/planning_intent.py#L401)（`validate_semantic_intent_hint`）；[learning_plan_tools.py:313](../../aearn/services/api/app/agents/runtime/learning_plan_tools.py#L313)（`LearningPlanRuntimeToolRegistry._invoke_context`）；[plan_tools.py:64](../../aearn/services/api/app/services/learning/plan_tools.py#L64)（`PlanningDirectionAction`）；[plan_tools.py:99](../../aearn/services/api/app/services/learning/plan_tools.py#L99)（`PlanningContextReadInput`）；[learning_plan_tools.py:376](../../aearn/services/api/app/agents/runtime/learning_plan_tools.py#L376)（`LearningPlanRuntimeToolRegistry._invoke_draft`）。
- **相关测试**：[test_codex_learning_plan_tools.py:287](../../aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools.py#L287)；[test_codex_learning_plan_tools_postgres.py:538](../../aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools_postgres.py#L538)；[test_codex_learning_plan_tools_postgres.py:575](../../aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools_postgres.py#L575)；[test_codex_learning_plan_tools.py:213](../../aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools.py#L213)。
- **边界**：语义推荐不能写成用户确认；能力元数据不能写成真实执行验收；不沿用旧版 Codex clarification_required 布尔字段描述当前封闭 direction_action。 单一accepted决议不是整个回合只允许一次context工具调用；confirmed_switch名称不证明已修改计划，draft另受非intake与continue_mainline约束。

### AG-04-003

[对应问题：学习计划是模型直接保存的吗？草稿、确认和能力校验如何衔接？](aearn-agent-design-handbook.md#ag-04-003)

- **核心结论**：计划候选经共享领域构建、事实与 catalog 校验后保存为草稿；确认最新精确版本才创建正式轨道。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[plan_tools.py:355](../../aearn/services/api/app/services/learning/plan_tools.py#L355)（`LearningPlanToolService.read_context`）；[plan_tools.py:575](../../aearn/services/api/app/services/learning/plan_tools.py#L575)（`LearningPlanToolService.draft`）；[plan_capability.py:212](../../aearn/services/api/app/services/learning/plan_capability.py#L212)（`build_validated_learning_plan_artifact`）；[plan_drafting.py:152](../../aearn/services/api/app/services/learning/plan_drafting.py#L152)（`build_plan_draft`）；[plan_service.py:214](../../aearn/services/api/app/services/learning/plan_service.py#L214)（`LearningPlanSessionService._confirm_session`）。
- **相关测试**：[test_learning_plan_draft_capability.py:110](../../aearn/services/api/tests/learning/test_learning_plan_draft_capability.py#L110)；[test_learning_plan_sessions.py:244](../../aearn/services/api/tests/learning/test_learning_plan_sessions.py#L244)；[test_learning_plan_sessions.py:959](../../aearn/services/api/tests/learning/test_learning_plan_sessions.py#L959)。
- **边界**：不能把 draft_completed 或 turn completed 当成学习计划已获用户确认；不能把计划校验写成完整教学或掌握度验收。

### AG-05-001

[对应问题：一次Tutor决策的上下文究竟来自哪里，为什么不能直接取聊天记录最后一条？](aearn-agent-design-handbook.md#ag-05-001)

- **核心结论**：当前上下文分基础、学习、Catalog三层；当前输入由run/input_revision的精确事件确定，控制与领域事件允许无文本输入。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[interactive.py:152](../../aearn/services/api/app/services/tutor/interactive.py#L152)（`PostgresTutorContextLoader.load_context`）；[interactive.py:468](../../aearn/services/api/app/services/tutor/interactive.py#L468)（`PostgresTutorContextLoader._load_current_input_row`）；[interactive.py:548](../../aearn/services/api/app/services/tutor/interactive.py#L548)（`PostgresTutorLearningContextLoader.load_context`）；[catalog_context.py:30](../../aearn/services/api/app/agents/harness/catalog_context.py#L30)（`CatalogContextLoader.load_context`）。
- **相关测试**：[test_tutor_context_loader.py:32](../../aearn/services/api/tests/tutor/test_tutor_context_loader.py#L32)；[test_tutor_context_loader.py:88](../../aearn/services/api/tests/tutor/test_tutor_context_loader.py#L88)。
- **边界**：不能声称每轮都读取全量历史或“模型能访问整个数据库”；这里只核对有界、预先限定scope的服务端读取。

### AG-05-002

[对应问题：预算不够时先保留什么、删掉什么？“必需上下文”是否绝不会被截断？](aearn-agent-design-handbook.md#ag-05-002)

- **核心结论**：默认1200字符/来源、近期4条；current_input可裁剪，必需分区对条数/检测到的字符截断/预算超限拒绝，但通用嵌套映射20项、列表12项的清洗不保证逐字段无损。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮另执行2例纯函数合成复核（13项列表保留12项、21字段映射保留20项，均未拒绝且truncated_count=0）；未执行所列pytest，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[contracts.py:110](../../aearn/services/api/app/agents/harness/contracts.py#L110)（`CONTEXT_SECTION_PRIORITY`）；[context_builder.py:34](../../aearn/services/api/app/agents/harness/context_builder.py#L34)（`DEFAULT_SECTION_ITEM_LIMITS`）；[context_builder.py:130](../../aearn/services/api/app/agents/harness/context_builder.py#L130)（`TutorContextBuilder.build`）；[context_builder.py:406](../../aearn/services/api/app/agents/harness/context_builder.py#L406)（`TutorContextBuilder._select_current_input`）；[interactive.py:965](../../aearn/services/api/app/services/tutor/interactive.py#L965)（`TutorInteractiveRunDispatcher.dispatch`）；[context_builder.py:559](../../aearn/services/api/app/agents/harness/context_builder.py#L559)（`_source_value_exceeds_limit`）；[context_builder.py:612](../../aearn/services/api/app/agents/harness/context_builder.py#L612)（`_sanitize_value`）。
- **相关测试**：[test_tutor_context_builder.py:324](../../aearn/services/api/tests/tutor/test_tutor_context_builder.py#L324)；[test_tutor_context_builder.py:418](../../aearn/services/api/tests/tutor/test_tutor_context_builder.py#L418)；[test_tutor_context_builder.py:452](../../aearn/services/api/tests/tutor/test_tutor_context_builder.py#L452)。
- **边界**：不能说任意required_facts逐字段无损；集合裁剪复核是合成纯函数边界，不证明真实会话已丢失事实。不能把1200字符等同token，未检查本机环境覆盖。

### AG-05-003

[对应问题：如何估算一次请求的token？只统计用户输入为什么不够？](aearn-agent-design-handbook.md#ag-05-003)

- **核心结论**：token估计采用UTF-8字节/4，共享messages序列化并加协议及安全预留；calibrate不重复加缓存token，也不自动调参。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[context_builder.py:110](../../aearn/services/api/app/agents/harness/context_builder.py#L110)（`Utf8ByteTokenEstimator.estimate_tokens`）；[context_budget.py:329](../../aearn/services/api/app/agents/harness/context_budget.py#L329)（`TutorContextBudgetPlanner._estimate_complete_request`）；[context_budget.py:275](../../aearn/services/api/app/agents/harness/context_budget.py#L275)（`TutorContextBudgetPlanner.calibrate`）；[provider_request.py:42](../../aearn/services/api/app/agents/harness/provider_request.py#L42)（`TutorProviderRequestSerializer.build_messages`）；[provider_gateway.py:223](../../aearn/services/api/app/services/tutor/provider_gateway.py#L223)（`PrimaryTutorProviderGateway.decide`）。
- **相关测试**：[test_tutor_context_budget.py:199](../../aearn/services/api/tests/tutor/test_tutor_context_budget.py#L199)；[test_tutor_context_budget.py:237](../../aearn/services/api/tests/tutor/test_tutor_context_budget.py#L237)；[test_tutor_context_budget.py:294](../../aearn/services/api/tests/tutor/test_tutor_context_budget.py#L294)。
- **边界**：不能把utf8_bytes_v1叫精确tokenizer、已验证误差上界或全HTTP请求严格计数；本轮未调用provider做校准。

### AG-05-004

[对应问题：百万上下文、128K输入和16K输出在项目中分别代表什么？](aearn-agent-design-handbook.md#ag-05-004)

- **核心结论**：精确deepseek-flash默认登记1,000,000物理窗口，应用input cap 131,072，输出预留61,440，决策输出16,384；Harness容量192,512与物理窗口不同。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[config.py:12](../../aearn/services/api/app/core/config.py#L12)（`DEEPSEEK_V4_FLASH_CONTEXT_WINDOW_TOKENS`）；[config.py:476](../../aearn/services/api/app/core/config.py#L476)（`Settings.uses_deepseek_v4_flash_responses`）；[config.py:483](../../aearn/services/api/app/core/config.py#L483)（`Settings.tutor_context_window_capacity_tokens`）；[config.py:525](../../aearn/services/api/app/core/config.py#L525)（`Settings.tutor_decision_max_output_tokens`）；[provider_gateway.py:148](../../aearn/services/api/app/services/tutor/provider_gateway.py#L148)（`PrimaryTutorProviderGateway.__init__`）。
- **相关测试**：[test_tutor_context_budget.py:93](../../aearn/services/api/tests/tutor/test_tutor_context_budget.py#L93)。
- **边界**：不能把代码能力登记称为供应商最新规格或实测支持；未读环境配置，不能声称本机当前运行的provider、cap或输出预算与默认值完全相同。

### AG-05-005

[对应问题：Aearn如何按任务复杂度分配上下文，而不是一直使用同一预算？](aearn-agent-design-handbook.md#ag-05-005)

- **核心结论**：四档分类使用确定性信号，optional预算取档位目标、动态上限、必需请求后余量最小值；默认扩展一次，水位按动态预算计算。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[context_budget.py:248](../../aearn/services/api/app/agents/harness/context_budget.py#L248)（`TutorContextBudgetPlanner.classify_mode`）；[context_budget.py:114](../../aearn/services/api/app/agents/harness/context_budget.py#L114)（`TutorContextBudgetPlanner.build_context`）；[context_budget.py:295](../../aearn/services/api/app/agents/harness/context_budget.py#L295)（`TutorContextBudgetPlanner._dynamic_thresholds`）；[run_loop.py:294](../../aearn/services/api/app/services/tutor/run_loop.py#L294)（`TutorRunLoop.run`）；[config.py:275](../../aearn/services/api/app/core/config.py#L275)（`Settings.tutor_context_compact_target_tokens`）。
- **相关测试**：[test_tutor_context_budget.py:144](../../aearn/services/api/tests/tutor/test_tutor_context_budget.py#L144)；[test_tutor_context_budget.py:169](../../aearn/services/api/tests/tutor/test_tutor_context_budget.py#L169)；[test_tutor_context_budget.py:263](../../aearn/services/api/tests/tutor/test_tutor_context_budget.py#L263)。
- **边界**：不能声称已实现token最优分配、成本降低比例或质量收益；规则与离线测试存在，本轮没有成本测量或真实任务对照实验。

### AG-05-006

[对应问题：聊天很长时如何压缩，怎样避免把尚未确认的事实压没？](aearn-agent-design-handbook.md#ag-05-006)

- **核心结论**：摘要压缩基于最多32候选中的受保护连续退休前缀，最多24条；独立于推断记忆且默认curation日/输出预算均为零。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[context_builder.py:340](../../aearn/services/api/app/agents/harness/context_builder.py#L340)（`TutorContextBuilder._build_compaction_input`）；[contracts.py:35](../../aearn/services/api/app/agents/harness/contracts.py#L35)（`MAX_TUTOR_CONTEXT_COMPACTION_MESSAGES`）；[interactive.py:655](../../aearn/services/api/app/services/tutor/interactive.py#L655)（`PostgresTutorLearningContextLoader.load_context`）；[curation.py:57](../../aearn/services/api/app/services/tutor/curation.py#L57)（`CurationContextSummaryProposalV2`）；[curation.py:182](../../aearn/services/api/app/services/tutor/curation.py#L182)（`PrimaryCurationGateway.propose`）；[learner_state.py:655](../../aearn/services/api/app/services/tutor/learner_state.py#L655)（`TutorLearnerStateRepository.latest_context_summary_for_conversation`）；[config.py:356](../../aearn/services/api/app/core/config.py#L356)（`Settings.tutor_curation_daily_budget`）；[config.py:359](../../aearn/services/api/app/core/config.py#L359)（`Settings.tutor_curation_max_output_tokens`）。
- **相关测试**：[test_tutor_context_builder.py:489](../../aearn/services/api/tests/tutor/test_tutor_context_builder.py#L489)；[test_tutor_context_summary.py:274](../../aearn/services/api/tests/tutor/test_tutor_context_summary.py#L274)；[test_tutor_context_summary.py:296](../../aearn/services/api/tests/tutor/test_tutor_context_summary.py#L296)；[test_tutor_context_summary.py:416](../../aearn/services/api/tests/tutor/test_tutor_context_summary.py#L416)。
- **边界**：不能把压缩envelope称为完整会话备份或已生成摘要，也不能声称默认开启长期自动记忆；本轮未执行后台任务或验证数据库投影。

### AG-05-007

[对应问题：把Lesson选区、执行结果或知识检查放进Prompt，如何避免越权和泄露？](aearn-agent-design-handbook.md#ag-05-007)

- **核心结论**：结构化引用先验证scope与来源，再保存有界安全快照独立注入；知识检查精确证据不得被普通摘要清洗悄悄改变。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[context_references.py:57](../../aearn/services/api/app/services/learning/context_references.py#L57)（`PostgresTutorContextReferenceRepository.record_for_input`）；[interactive.py:599](../../aearn/services/api/app/services/tutor/interactive.py#L599)（`PostgresTutorLearningContextLoader.load_context`）；[context_builder.py:459](../../aearn/services/api/app/agents/harness/context_builder.py#L459)（`TutorContextBuilder._serialize_source`）；[context_builder.py:591](../../aearn/services/api/app/agents/harness/context_builder.py#L591)（`_redact_harness_sensitive_fields`）；[provider_request.py:115](../../aearn/services/api/app/agents/harness/provider_request.py#L115)（`TutorProviderRequestSerializer.build_messages`）；[context_references.py:359](../../aearn/services/api/app/services/learning/context_references.py#L359)（`PostgresTutorContextReferenceRepository._lesson_selection`）。
- **相关测试**：[test_tutor_context_references.py:113](../../aearn/services/api/tests/tutor/test_tutor_context_references.py#L113)；[test_tutor_context_references.py:348](../../aearn/services/api/tests/tutor/test_tutor_context_references.py#L348)；[test_tutor_context_builder.py:88](../../aearn/services/api/tests/tutor/test_tutor_context_builder.py#L88)。
- **边界**：不能声称模型看见完整隐藏测试、原始stdout或任意客户端payload，也不能把hash与脱敏描述为完整提示注入防护证明。

### AG-05-008

[对应问题：Codex线程压缩、Harness压缩envelope和Teaching checkpoint是不是一回事？](aearn-agent-design-handbook.md#ag-05-008)

- **核心结论**：Codex线程压缩配置、Harness后台摘要envelope与TeachingSession checkpoint分别拥有运行时连续性、摘要调度和教学authority，互不替代。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[codex_config.py:36](../../aearn/services/api/app/agents/runtime/codex_config.py#L36)（`CodexRuntimeConfig`）；[codex_config.py:135](../../aearn/services/api/app/agents/runtime/codex_config.py#L135)（`ensure_codex_runtime_home`）；[curation.py:154](../../aearn/services/api/app/services/tutor/persistence/curation.py#L154)（`CurationPersistenceMixin._persist_checkpoint_and_outbox_locked`）；[teaching_sessions.py:1411](../../aearn/services/api/app/services/learning/teaching_sessions.py#L1411)（`TeachingSessionRepository._insert_checkpoint`）；[teaching_sessions.py:614](../../aearn/services/api/app/services/learning/teaching_sessions.py#L614)（`TeachingSessionRepository.structured_summary`）。
- **相关测试**：[test_codex_runtime_config.py:41](../../aearn/services/api/tests/codex_sidecar/test_codex_runtime_config.py#L41)；[test_codex_runtime_config.py:57](../../aearn/services/api/tests/codex_sidecar/test_codex_runtime_config.py#L57)；[test_tutor_context_summary.py:274](../../aearn/services/api/tests/tutor/test_tutor_context_summary.py#L274)；[test_tutor_teaching_sessions.py:69](../../aearn/services/api/tests/tutor/test_tutor_teaching_sessions.py#L69)。
- **边界**：不能说Harness自身拥有Codex线程压缩机制，也不能用外部线程compaction成功替代Aearn业务恢复验收；本题不把本项目配置推广为所有上游版本的通用能力。

### AG-06-001

[对应问题：长期记忆是什么，模型能不能自行给学习者写一个永久标签？](aearn-agent-design-handbook.md#ag-06-001)

- **核心结论**：长期记忆区分objective_fact与inference，推断写入经curation租约/版本验证；用户可追加更正或状态删除，active读取未直接按TTL过滤。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[learner_state.py:89](../../aearn/services/api/app/services/tutor/learner_state.py#L89)（`TutorMemoryEntry`）；[learner_state.py:414](../../aearn/services/api/app/services/tutor/learner_state.py#L414)（`TutorLearnerStateRepository.record_objective_memory_from_effect`）；[learner_state.py:591](../../aearn/services/api/app/services/tutor/learner_state.py#L591)（`TutorLearnerStateRepository.correct_memory_entry`）；[learner_state.py:1151](../../aearn/services/api/app/services/tutor/learner_state.py#L1151)（`TutorLearnerStateRepository.commit_inference_memory_projection`）；[learner_state.py:1326](../../aearn/services/api/app/services/tutor/learner_state.py#L1326)（`TutorLearnerStateRepository.list_memory_entries`）；[config.py:350](../../aearn/services/api/app/core/config.py#L350)（`Settings.tutor_inferred_memory_enabled`）。
- **相关测试**：[test_tutor_memory.py:17](../../aearn/services/api/tests/tutor/test_tutor_memory.py#L17)；[test_tutor_memory.py:97](../../aearn/services/api/tests/tutor/test_tutor_memory.py#L97)；[test_tutor_memory_curation_scheduler.py:182](../../aearn/services/api/tests/tutor/test_tutor_memory_curation_scheduler.py#L182)。
- **边界**：不能声称默认长期自动记忆已开启、所有记忆天然正确或过期必定立即不可见；本题明确只读查询的时间过滤边界。

### AG-06-002

[对应问题：工作摘要、学习者记忆和课程状态冲突时，谁说了算？](aearn-agent-design-handbook.md#ag-06-002)

- **核心结论**：摘要与记忆是辅助证据；规划事实和教学progress/checkpoint由领域服务持有，完成暂停与重复规划提问由业务gate确定性约束。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[provider_request.py:24](../../aearn/services/api/app/agents/harness/provider_request.py#L24)（`TUTOR_TEACHING_POLICY`）；[planning_facts.py:514](../../aearn/services/api/app/services/learning/planning_facts.py#L514)（`PostgresPlanningFactRepository.project_snapshot`）；[planning_facts.py:810](../../aearn/services/api/app/services/learning/planning_facts.py#L810)（`PlanningQuestionDecisionGate.validate`）；[teaching_sessions.py:614](../../aearn/services/api/app/services/learning/teaching_sessions.py#L614)（`TeachingSessionRepository.structured_summary`）；[decision_gate.py:410](../../aearn/services/api/app/services/tutor/decision_gate.py#L410)（`TeachingTutorDecisionGate.validate`）；[context_builder.py:612](../../aearn/services/api/app/agents/harness/context_builder.py#L612)（`_sanitize_value`）。
- **相关测试**：[test_teaching_completion_prompt.py:95](../../aearn/services/api/tests/tutor/test_teaching_completion_prompt.py#L95)；[test_teaching_completion_prompt.py:116](../../aearn/services/api/tests/tutor/test_teaching_completion_prompt.py#L116)；[test_tutor_context_builder.py:418](../../aearn/services/api/tests/tutor/test_tutor_context_builder.py#L418)。
- **边界**：不能把客观记忆、模型摘要中的confirmed_facts、教学covered_concepts或一段表扬等同于独立mastery/评分/进度证明。 必需上下文的预算门禁不等于通用嵌套对象无损；集合清洗边界见AG-05-002。

### AG-06-003

[对应问题：同一条长期对话中，知识点切换和Artifact澄清分支怎样避免串状态？](aearn-agent-design-handbook.md#ag-06-003)

- **核心结论**：TeachingSession和Artifact分支用精确scope/checkpoint隔离业务状态；控制事件历史同session过滤，普通learner输入history仍是conversation级。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[teaching_sessions.py:707](../../aearn/services/api/app/services/learning/teaching_sessions.py#L707)（`TeachingSessionRepository.teaching_context`）；[interactive.py:329](../../aearn/services/api/app/services/tutor/interactive.py#L329)（`PostgresTutorContextLoader._load_teaching_recent_messages`）；[interactive.py:218](../../aearn/services/api/app/services/tutor/interactive.py#L218)（`PostgresTutorContextLoader.load_context`）；[branching.py:100](../../aearn/services/api/app/services/tutor/branching.py#L100)（`PostgresTutorBranchRepository.bind_turn`）；[branching.py:922](../../aearn/services/api/app/services/tutor/branching.py#L922)（`PostgresTutorBranchRepository._active_artifact_scope`）；[branching.py:267](../../aearn/services/api/app/services/tutor/branching.py#L267)（`PostgresTutorBranchRepository.complete_turn`）；[config.py:320](../../aearn/services/api/app/core/config.py#L320)（`Settings.tutor_learning_artifacts_enabled`）；[config.py:326](../../aearn/services/api/app/core/config.py#L326)（`Settings.tutor_artifact_teaching_mode_enabled`）。
- **相关测试**：[test_tutor_teaching_context.py:100](../../aearn/services/api/tests/tutor/test_tutor_teaching_context.py#L100)；[test_tutor_teaching_sessions.py:69](../../aearn/services/api/tests/tutor/test_tutor_teaching_sessions.py#L69)；[test_tutor_branch_continuation.py:596](../../aearn/services/api/tests/tutor/test_tutor_branch_continuation.py#L596)；[test_tutor_branch_continuation.py:1045](../../aearn/services/api/tests/tutor/test_tutor_branch_continuation.py#L1045)。
- **边界**：不能声称全部历史、摘要和用户记忆在知识点间物理隔离；当前严格限定的是教学与分支权威，普通用户输入的可选历史仍按conversation连续读取。

### AG-07-001

[对应问题：Aearn 当前实际怎样检索知识，能称为混合检索吗？](aearn-agent-design-handbook.md#ag-07-001)

- **核心结论**：持久化 grounding 先按语言读 chunk，课程准入过滤在排序前；Python 词项/主题/信任偏好打分及同语言 fallback，不是混合向量检索。
- **实现状态**：当前实现为确定性词项排序；RAG 2.0 混合检索为规划
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[grounding_retrieval.py:29](../../aearn/services/api/app/services/grounding/grounding_retrieval.py#L29)（`retrieve_grounding_chunks`）；[grounding_retrieval.py:60](../../aearn/services/api/app/services/grounding/grounding_retrieval.py#L60)（`_score_chunk`）；[grounding_retrieval.py:106](../../aearn/services/api/app/services/grounding/grounding_retrieval.py#L106)（`_terms`）；[grounding_index_repository.py:131](../../aearn/services/api/app/services/grounding/grounding_index_repository.py#L131)（`search_persisted_grounding_chunks`）；[grounding_index_repository.py:239](../../aearn/services/api/app/services/grounding/grounding_index_repository.py#L239)（`grounding_language_ids`）；[grounding_index_repository.py:247](../../aearn/services/api/app/services/grounding/grounding_index_repository.py#L247)（`_load_grounding_chunks_for_languages`）；[grounding_reindex.py:37](../../aearn/services/api/app/services/grounding/grounding_reindex.py#L37)（`run_grounding_reindex`）；[lesson_authoring.py:419](../../aearn/services/api/app/services/learning/lesson_authoring.py#L419)（`_load_evidence_snapshots`）。
- **相关测试**：[test_grounding_retrieval.py:37](../../aearn/services/api/tests/grounding/test_grounding_retrieval.py#L37)（`test_retrieval_filters_to_requested_language`）；[test_grounding_retrieval.py:48](../../aearn/services/api/tests/grounding/test_grounding_retrieval.py#L48)（`test_query_and_topic_matches_improve_ranking`）；[test_grounding_retrieval.py:89](../../aearn/services/api/tests/grounding/test_grounding_retrieval.py#L89)（`test_empty_or_no_hit_query_falls_back_to_same_language_chunks`）；[test_grounding_index_repository.py:139](../../aearn/services/api/tests/grounding/test_grounding_index_repository.py#L139)（`test_html_css_public_course_language_searches_html_and_css_indexes`）。
- **边界**：版本标签不是精确 corpus/version 过滤；fallback 数量不等于相关性或覆盖；无向量检索/reranker 已实现声明。

### AG-07-002

[对应问题：如何证明课程引用来自可信资料，而不是模型生成了一个看似官方的链接？](aearn-agent-design-handbook.md#ag-07-002)

- **核心结论**：新课程只接收合格来源证明，LessonDocument 保存来源快照和 block 引用，历史读取不等于新教材准入。
- **实现状态**：当前实现
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[grounding_fetcher.py:100](../../aearn/services/api/app/services/grounding/grounding_fetcher.py#L100)（`GroundingDocsFetcher.fetch`）；[grounding_fetcher.py:66](../../aearn/services/api/app/services/grounding/grounding_fetcher.py#L66)（`HttpxGroundingHttpClient.get`）；[grounding_processing.py:137](../../aearn/services/api/app/services/grounding/grounding_processing.py#L137)（`clean_and_chunk_document`）；[grounding_processing.py:184](../../aearn/services/api/app/services/grounding/grounding_processing.py#L184)（`is_admissible_lesson_source`）；[lesson_authoring.py:419](../../aearn/services/api/app/services/learning/lesson_authoring.py#L419)（`_load_evidence_snapshots`）；[lesson_repository.py:540](../../aearn/services/api/app/services/learning/lesson_repository.py#L540)（`PostgresLessonDocumentRepository._insert_document_children`）；[lesson_repository.py:402](../../aearn/services/api/app/services/learning/lesson_repository.py#L402)（`PostgresLessonDocumentRepository.load_source_snapshots`）。
- **相关测试**：[test_lesson_source_provenance.py:67](../../aearn/services/api/tests/learning/test_lesson_source_provenance.py#L67)（`test_historical_or_malformed_metadata_is_readable_but_never_admitted`）；[test_lesson_source_provenance.py:79](../../aearn/services/api/tests/learning/test_lesson_source_provenance.py#L79)（`test_fixture_identity_is_stable_and_only_explicit_offline_seam_accepts_it`）；[test_lesson_source_provenance.py:97](../../aearn/services/api/tests/learning/test_lesson_source_provenance.py#L97)（`test_mismatched_evidence_fails_closed`）；[test_lesson_source_provenance.py:106](../../aearn/services/api/tests/learning/test_lesson_source_provenance.py#L106)（`test_injected_transport_does_not_claim_real_ingestion`）。
- **边界**：哈希证明身份而非真伪；fixture 或 Mock HTTP 不能算真实联网验收；来源快照不是 RAG 2.0 的 corpus 发布体系。

### AG-07-003

[对应问题：既有 grounding 能力、Tutor 实际入口与 RAG 2.0 规划应该怎样分开讲？](aearn-agent-design-handbook.md#ag-07-003)

- **核心结论**：课程生成已有持久化检索；交互 dispatcher 注入空 InMemoryGroundingLookup，实际策略不开放 grounding；RAG 2.0 新范围仍为 planning。
- **实现状态**：已有底层检索和受控接口；交互 grounding 未开放；RAG 2.0 规划
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；RAG planning 状态为同日本地任务检查，不属于源码提交内容；核对日期 2026-09-16。
- **源码/规格**：[interactive.py:936](../../aearn/services/api/app/services/tutor/interactive.py#L936)（`TutorInteractiveRunDispatcher.dispatch`）；[grounding_lookup.py:54](../../aearn/services/api/app/services/tutor/grounding_lookup.py#L54)（`InMemoryGroundingLookup.__init__`）；[plan_policy.py:39](../../aearn/services/api/app/services/learning/plan_policy.py#L39)（`InteractiveLearningCapabilityPolicyResolver.resolve`）；[capability_gateway.py:103](../../aearn/services/api/app/services/tutor/capability_gateway.py#L103)（`CatalogCapabilityGateway._dispatch_grounding`）；[capabilities.py:41](../../aearn/services/api/app/agents/harness/capabilities.py#L41)（`GroundingRetrieveInput`）；[prd.md:5](../../.trellis/tasks/09-03-rag-bounded-hybrid-retrieval-coverage/prd.md#L5)（`Goal / Requirements`）；[task.json:6](../../.trellis/tasks/09-03-rag-bounded-hybrid-retrieval-coverage/task.json#L6)（`status`）。
- **相关测试**：[test_tutor_grounding_policy.py:129](../../aearn/services/api/tests/grounding/test_tutor_grounding_policy.py#L129)（`test_grounding_retrieve_uses_registry_scope_and_returns_bounded_citation_facts`）；[test_tutor_grounding_policy.py:285](../../aearn/services/api/tests/grounding/test_tutor_grounding_policy.py#L285)（`test_grounding_rejects_extra_or_target_like_input_before_lookup`）。
- **边界**：task status 不能证明整个项目无 RAG；测试适配器不等于产品接线；未检查当前实例环境开关。

### AG-08-001

[对应问题：为什么同时有Prompt、Skill和Capability，不直接写一个大system prompt？](aearn-agent-design-handbook.md#ag-08-001)

- **核心结论**：Prompt承担机器协议，Skill按精确版本/hash按需装载，Capability按策略/runtime/预算暴露；Catalog加载不保证长指令不被后续builder裁剪。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[provider_request.py:42](../../aearn/services/api/app/agents/harness/provider_request.py#L42)（`TutorProviderRequestSerializer.build_messages`）；[catalog_context.py:30](../../aearn/services/api/app/agents/harness/catalog_context.py#L30)（`CatalogContextLoader.load_context`）；[catalog_context.py:97](../../aearn/services/api/app/agents/harness/catalog_context.py#L97)（`CatalogContextLoader._selected_skill`）；[decision_gate.py:54](../../aearn/services/api/app/services/tutor/decision_gate.py#L54)（`CatalogTutorDecisionGate.validate`）；[context_builder.py:459](../../aearn/services/api/app/agents/harness/context_builder.py#L459)（`TutorContextBuilder._serialize_source`）。
- **相关测试**：[test_tutor_provider_gateway.py:1287](../../aearn/services/api/tests/tutor/test_tutor_provider_gateway.py#L1287)；[test_tutor_skill_catalog.py:66](../../aearn/services/api/tests/tutor/test_tutor_skill_catalog.py#L66)；[test_teaching_selected_skill_repair.py:196](../../aearn/services/api/tests/tutor/test_teaching_selected_skill_repair.py#L196)。
- **边界**：不能把Skill存在说成模型能访问所有工具，也不能声称长Skill全文必定进入Prompt；分层机制不等于已证明教学质量最优。

### AG-08-002

[对应问题：Skill版本如何保证可复现？为什么不能直接修改旧instructions再重算hash？](aearn-agent-design-handbook.md#ag-08-002)

- **核心结论**：Skill验证精确SemVer目录与资源SHA-256；TeachingTutorDecisionGate固定1.2.1、manifest输出v3，旧bundle保留；部分文档仍写1.2.0或1.1.0/v2，不可据此解释现役契约。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[skill_catalog.py:265](../../aearn/services/api/app/agents/harness/skill_catalog.py#L265)（`SkillCatalogCompiler.compile`）；[skill_catalog.py:304](../../aearn/services/api/app/agents/harness/skill_catalog.py#L304)（`SkillCatalogCompiler._compile_bundle`）；[skill_catalog.py:422](../../aearn/services/api/app/agents/harness/skill_catalog.py#L422)（`_validate_evaluation_suite`）；[catalog_context.py:97](../../aearn/services/api/app/agents/harness/catalog_context.py#L97)（`CatalogContextLoader._selected_skill`）；[manifest.json:2](../../aearn/services/api/app/agents/skills/tutor.lesson-teaching/1.2.1/manifest.json#L2)（`tutor.lesson-teaching@1.2.1 manifest`）；[decision_gate.py:264](../../aearn/services/api/app/services/tutor/decision_gate.py#L264)（`TeachingTutorDecisionGate`）。
- **相关测试**：[test_tutor_skill_catalog.py:66](../../aearn/services/api/tests/tutor/test_tutor_skill_catalog.py#L66)；[test_tutor_skill_catalog.py:99](../../aearn/services/api/tests/tutor/test_tutor_skill_catalog.py#L99)；[test_tutor_skill_catalog.py:193](../../aearn/services/api/tests/tutor/test_tutor_skill_catalog.py#L193)；[test_tutor_skill_catalog.py:288](../../aearn/services/api/tests/tutor/test_tutor_skill_catalog.py#L288)。
- **边界**：不能把文件系统称为防篡改存储，也不能把eval声明存在说成已完成评估；当前教学版本应以1.2.1为准，历史版本不应改写。 docs/README.md:16及.trellis/spec/backend/teaching-session-authority.md:25-28、79、288存在旧版本说明，未在本轮越权修改。

### AG-08-003

[对应问题：模型输出合法JSON就能执行业务动作吗？决策协议怎样分层验证？](aearn-agent-design-handbook.md#ag-08-003)

- **核心结论**：provider items v5严格解析并由服务端组装控制字段；教学语义、Catalog授权、当前authority与提交fence独立验证，gateway决策修复最多两次尝试。
- **实现状态**：当前实现
- **验证状态**：源码、默认配置与所列测试用例核对；本轮未执行这些运行时测试，未做provider或数据库验收；核对日期 2026-09-16。
- **源码/规格**：[decision_protocol.py:47](../../aearn/services/api/app/services/tutor/decision_protocol.py#L47)（`TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION`）；[decision_protocol.py:149](../../aearn/services/api/app/services/tutor/decision_protocol.py#L149)（`_StrictProviderModel`）；[decision_protocol.py:707](../../aearn/services/api/app/services/tutor/decision_protocol.py#L707)（`_teaching_step_semantic_issues`）；[decision_protocol.py:766](../../aearn/services/api/app/services/tutor/decision_protocol.py#L766)（`parse_tutor_provider_items`）；[decision_gate.py:286](../../aearn/services/api/app/services/tutor/decision_gate.py#L286)（`TeachingTutorDecisionGate.validate`）；[provider_gateway.py:67](../../aearn/services/api/app/services/tutor/provider_gateway.py#L67)（`PRIMARY_PROVIDER_DECISION_ATTEMPTS`）；[run_loop.py:305](../../aearn/services/api/app/services/tutor/run_loop.py#L305)（`TutorRunLoop.run`）；[config.py:237](../../aearn/services/api/app/core/config.py#L237)（`Settings.tutor_deepseek_responses_json_schema_enabled`）。
- **相关测试**：[test_teaching_decision_semantic_feedback.py:131](../../aearn/services/api/tests/tutor/test_teaching_decision_semantic_feedback.py#L131)；[test_teaching_decision_semantic_feedback.py:157](../../aearn/services/api/tests/tutor/test_teaching_decision_semantic_feedback.py#L157)；[test_tutor_provider_gateway.py:1287](../../aearn/services/api/tests/tutor/test_tutor_provider_gateway.py#L1287)；[test_teaching_completion_prompt.py:116](../../aearn/services/api/tests/tutor/test_teaching_completion_prompt.py#L116)。
- **边界**：不能把合法JSON、通过schema、返回200、产生公开message或provider修复成功等同于评分、进度或真实业务提交成功。

### AG-09-001

[对应问题：Skill、capability、effect 与服务端权限是什么关系？](aearn-agent-design-handbook.md#ag-09-001)

- **核心结论**：Skill 是精确行为包，capability/effect 是受控请求或提案；catalog、policy、输入 schema、runtime 与预算共同限制执行。
- **实现状态**：当前实现
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[decision_gate.py:205](../../aearn/services/api/app/services/tutor/decision_gate.py#L205)（`CatalogTutorDecisionGate._validate_capability_requests`）；[decision_gate.py:225](../../aearn/services/api/app/services/tutor/decision_gate.py#L225)（`CatalogTutorDecisionGate._validate_effect_proposals`）；[capability_gateway.py:58](../../aearn/services/api/app/services/tutor/capability_gateway.py#L58)（`CatalogCapabilityGateway.dispatch`）；[capability_policy.py:63](../../aearn/services/api/app/services/tutor/capability_policy.py#L63)（`CapabilityPolicyContext.matches`）；[capability_policy.py:75](../../aearn/services/api/app/services/tutor/capability_policy.py#L75)（`CapabilityPolicyContext.allows_descriptor`）；[plan_policy.py:39](../../aearn/services/api/app/services/learning/plan_policy.py#L39)（`InteractiveLearningCapabilityPolicyResolver.resolve`）；[capability_gateway.py:165](../../aearn/services/api/app/services/tutor/capability_gateway.py#L165)（`CatalogCapabilityGateway._dispatch_learning_plan`）。
- **相关测试**：[test_tutor_grounding_policy.py:301](../../aearn/services/api/tests/grounding/test_tutor_grounding_policy.py#L301)（`test_grounding_denies_policy_and_reports_runtime_unavailable_without_lookup`）。
- **边界**：Prompt 不授予权限；READ 标签不保证领域零写入；注册能力不代表当前入口已开放。

### AG-09-002

[对应问题：模型提出写操作后，如何防止过期结果和重试产生重复副作用？](aearn-agent-design-handbook.md#ag-09-002)

- **核心结论**：effect 在事务内验证 revision/lease/teaching scope，并按请求身份及 retry-root 逻辑键去重；领域 handler 和结果事件同连接提交。
- **实现状态**：通用 effect 基础设施已实现；当前交互 effect 默认拒绝
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[effects.py:305](../../aearn/services/api/app/services/tutor/persistence/effects.py#L305)（`EffectsPersistenceMixin.commit_effect_if_current`）；[effects.py:971](../../aearn/services/api/app/services/tutor/persistence/effects.py#L971)（`EffectsPersistenceMixin._selected_skill_allows_effect`）；[interactive.py:936](../../aearn/services/api/app/services/tutor/interactive.py#L936)（`TutorInteractiveRunDispatcher.dispatch`）。
- **相关测试**：[test_tutor_effect_commit.py:19](../../aearn/services/api/tests/tutor/test_tutor_effect_commit.py#L19)（`test_effect_cas_rejects_stale_revision_or_lease_without_invoking_domain_handler`）；[test_tutor_effect_commit.py:147](../../aearn/services/api/tests/tutor/test_tutor_effect_commit.py#L147)（`test_retry_lineage_reuses_committed_logical_effect_without_second_domain_write`）。
- **边界**：当前 interactive 注入 DefaultDenyEffectCommitter；业务提交去重不是模型、工具或外部 API 物理执行一次。

### AG-09-003

[对应问题：学习者点击 Run 时，执行授权为什么不能只靠前端按钮？](aearn-agent-design-handbook.md#ag-09-003)

- **核心结论**：Artifact Run 要经精确 owner/CAS 校验；SQL owner 只持久化 pending Attempt，路由提交后才在独立 SQLite 执行并统一评分，run 类型不推进 Gate。
- **实现状态**：当前实现，Artifact 两个开关源码默认关闭
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[repository.py:759](../../aearn/services/api/app/services/learning/artifacts/repository.py#L759)（`PostgresLearningArtifactRepository.apply_action`）；[sql_workspaces.py:60](../../aearn/services/api/app/services/learning/artifacts/sql_workspaces.py#L60)（`admit_sql_workspace_run`）；[sql_workspaces.py:184](../../aearn/services/api/app/services/learning/artifacts/sql_workspaces.py#L184)（`observe_sql_workspace_attempt`）；[learning_artifacts.py:110](../../aearn/services/api/app/routes/learning_artifacts.py#L110)（`act_on_learning_artifact`）；[repository.py:903](../../aearn/services/api/app/services/learning/practice/repository.py#L903)（`PostgresExerciseGateRepository.finalize_gate_attempt`）；[sql_query_runner.py:243](../../aearn/services/api/app/services/runners/sql_query_runner.py#L243)（`execute_sql_workspace_query`）；[config.py:320](../../aearn/services/api/app/core/config.py#L320)（`Settings.tutor_learning_artifacts_enabled`）；[config.py:326](../../aearn/services/api/app/core/config.py#L326)（`Settings.tutor_artifact_teaching_mode_enabled`）。
- **相关测试**：[test_tutor_teaching_artifact_commit.py:1352](../../aearn/services/api/tests/tutor/test_tutor_teaching_artifact_commit.py#L1352)（`test_sql_workspace_action_route_executes_only_after_admission_commit`）。
- **边界**：仅以 SQL 路径举例，不推广所有语言隔离能力；并发 observer 可重复计算但结果终结去重；源码默认开关关闭，不检查实例配置。

### AG-10-001

[对应问题：为什么教学 checkpoint 不能只放在模型历史或进程内存里？](aearn-agent-design-handbook.md#ag-10-001)

- **核心结论**：TeachingSession/checkpoint/教材/进度绑定具体 run 权威；terminal transaction 追加 checkpoint、CAS session、写消息回执/Artifact 并终结 run。
- **实现状态**：当前实现
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[teaching_sessions.py:582](../../aearn/services/api/app/services/learning/teaching_sessions.py#L582)（`TeachingSessionRepository.assert_run_scope_current`）；[effects.py:685](../../aearn/services/api/app/services/tutor/persistence/effects.py#L685)（`EffectsPersistenceMixin._commit_teaching_step_locked`）；[effects.py:813](../../aearn/services/api/app/services/tutor/persistence/effects.py#L813)（`EffectsPersistenceMixin._finalize_teaching_step_locked`）；[run.py:706](../../aearn/services/api/app/services/tutor/persistence/run.py#L706)（`RunPersistenceMixin.complete_run`）。
- **相关测试**：[test_tutor_teaching_artifact_commit.py:1075](../../aearn/services/api/tests/tutor/test_tutor_teaching_artifact_commit.py#L1075)（`test_publication_change_after_decision_context_rolls_back_message_checkpoint_and_artifact`）；[test_tutor_teaching_artifact_commit.py:1152](../../aearn/services/api/tests/tutor/test_tutor_teaching_artifact_commit.py#L1152)（`test_artifact_event_failure_after_message_insert_rolls_back_every_public_write`）。
- **边界**：业务 checkpoint 不是聊天摘要；旧权威不能覆盖新课程，源码事务与回滚测试不是本轮容灾实测。

### AG-10-002

[对应问题：同一 Conversation 收到新输入后，Turn 与 input_revision 怎样阻止旧结果提交？](aearn-agent-design-handbook.md#ag-10-002)

- **核心结论**：run 内输入按幂等键/正文哈希重放并 CAS revision；thread_turn_v2 普通新消息创建新 Turn 并替代旧前台 run；lease generation 与边界复查阻止旧结果提交。
- **实现状态**：当前实现，明确区分 run revision 与 thread_turn_v2 分支
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[run.py:292](../../aearn/services/api/app/services/tutor/persistence/run.py#L292)（`RunPersistenceMixin.accept_input`）；[run.py:123](../../aearn/services/api/app/services/tutor/persistence/run.py#L123)（`RunPersistenceMixin.acquire_lease`）；[run.py:164](../../aearn/services/api/app/services/tutor/persistence/run.py#L164)（`RunPersistenceMixin.heartbeat_lease`）；[run.py:706](../../aearn/services/api/app/services/tutor/persistence/run.py#L706)（`RunPersistenceMixin.complete_run`）；[interaction.py:115](../../aearn/services/api/app/services/tutor/persistence/interaction.py#L115)（`InteractionPersistenceMixin.create_interactive_turn`）；[interaction.py:152](../../aearn/services/api/app/services/tutor/persistence/interaction.py#L152)（`InteractionPersistenceMixin._create_interactive_turn_locked`）；[run_loop.py:90](../../aearn/services/api/app/services/tutor/run_loop.py#L90)（`TutorRunLoop.run`）；[run_loop.py:524](../../aearn/services/api/app/services/tutor/run_loop.py#L524)（`TutorRunLoop._refresh_before_unsafe_boundary`）。
- **相关测试**：[test_tutor_run_repository.py:142](../../aearn/services/api/tests/tutor/test_tutor_run_repository.py#L142)（`test_accept_input_rejects_a_cancelled_run_before_writing_raw_content`）；[test_tutor_run_repository.py:212](../../aearn/services/api/tests/tutor/test_tutor_run_repository.py#L212)（`test_expired_lease_owner_can_renew_only_before_replacement_claim`）；[test_tutor_run_loop.py:502](../../aearn/services/api/tests/tutor/test_tutor_run_loop.py#L502)（`test_post_provider_supersede_stops_before_decision_capability_effect_or_terminal_write`）。
- **边界**：不同 admission 的幂等范围不能混用；晚续租只限无新代次接管；拒绝晚结果不表示外部调用未执行或已停止。

### AG-10-003

[对应问题：自动续教如何恢复而不重复开回合，也不抢走学习者正在进行的交互？](aearn-agent-design-handbook.md#ag-10-003)

- **核心结论**：精确 immutable stimulus 与持久化 continuation intent 分离；固定优先级/前台/分支围栏控制 claim，开 run 与消费 claim 在事务内关联。
- **实现状态**：当前实现
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[teaching_sessions.py:1432](../../aearn/services/api/app/services/learning/teaching_sessions.py#L1432)（`TeachingSessionRepository._insert_stimulus_scope`）；[continuation.py:47](../../aearn/services/api/app/services/tutor/continuation.py#L47)（`CONTINUATION_PRIORITY`）；[continuation.py:347](../../aearn/services/api/app/services/tutor/continuation.py#L347)（`PostgresTutorContinuationIntentRepository.claim_next`）；[continuation.py:437](../../aearn/services/api/app/services/tutor/continuation.py#L437)（`PostgresTutorContinuationIntentRepository.consume_claim`）；[continuation.py:1367](../../aearn/services/api/app/services/tutor/continuation.py#L1367)（`TutorContinuationDispatcher.dispatch_next`）。
- **相关测试**：[test_tutor_branch_continuation.py:670](../../aearn/services/api/tests/tutor/test_tutor_branch_continuation.py#L670)（`test_two_competing_claimants_get_one_claim_and_producer_creates_no_turn`）；[test_tutor_branch_continuation.py:739](../../aearn/services/api/tests/tutor/test_tutor_branch_continuation.py#L739)（`test_fixed_priority_preempts_claimed_work_and_then_drains_in_order`）；[test_tutor_branch_continuation.py:1674](../../aearn/services/api/tests/tutor/test_tutor_branch_continuation.py#L1674)（`test_automatic_intents_are_guided_only_and_stale_authority_fails_closed`）。
- **边界**：抢占未消费 claim 不等于硬中断运行模型；control/event 不伪造 learner message；受理不是教学或 Gate 完成。

### AG-11-001

[对应问题：一次正式 Gate 提交怎样更新 Attempt、掌握度与课程进度？](aearn-agent-design-handbook.md#ag-11-001)

- **核心结论**：正式 Gate finalizer 用权威 Attempt result 和当前课程范围判断阈值、追加独立性证据，required Gates 全过才推进节点；普通 Run 不进入该投影。
- **实现状态**：当前实现
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[repository.py:903](../../aearn/services/api/app/services/learning/practice/repository.py#L903)（`PostgresExerciseGateRepository.finalize_gate_attempt`）；[repository.py:1083](../../aearn/services/api/app/services/learning/practice/repository.py#L1083)（`PostgresExerciseGateRepository._unlock_available_nodes`）；[repository.py:1115](../../aearn/services/api/app/services/learning/practice/repository.py#L1115)（`PostgresExerciseGateRepository._advance_track`）；[decision_gate.py:286](../../aearn/services/api/app/services/tutor/decision_gate.py#L286)（`TeachingTutorDecisionGate.validate`）。
- **相关测试**：[test_exercise_gate_repository.py:45](../../aearn/services/api/tests/learning/test_exercise_gate_repository.py#L45)（`test_required_gate_submit_updates_mastery_and_completes_node`）。
- **边界**：Artifact completed、Run passed、Gate passed、独立掌握和路线完成率不同；无本轮真实主线进度声明。

### AG-11-002

[对应问题：用 Hint、看答案、做补救题之后，如何避免把“被帮助的正确”算成独立掌握？](aearn-agent-design-handbook.md#ag-11-002)

- **核心结论**：KC 按发布题目私有规则确定性评分；Hints/direct answer/remediation 单独记账，后继按发布状态、难度、能力范围及未使用约束选择。
- **实现状态**：当前实现
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[knowledge_checks.py:123](../../aearn/services/api/app/services/learning/artifacts/knowledge_checks.py#L123)（`_apply_hint`）；[knowledge_checks.py:159](../../aearn/services/api/app/services/learning/artifacts/knowledge_checks.py#L159)（`_apply_direct_answer`）；[knowledge_checks.py:222](../../aearn/services/api/app/services/learning/artifacts/knowledge_checks.py#L222)（`_apply_response`）；[knowledge_checks.py:319](../../aearn/services/api/app/services/learning/artifacts/knowledge_checks.py#L319)（`_score`）；[knowledge_checks.py:490](../../aearn/services/api/app/services/learning/artifacts/knowledge_checks.py#L490)（`_select_remediation`）；[knowledge_checks.py:512](../../aearn/services/api/app/services/learning/artifacts/knowledge_checks.py#L512)（`_select_transfer`）；[knowledge_checks.py:528](../../aearn/services/api/app/services/learning/artifacts/knowledge_checks.py#L528)（`_select_successor`）。
- **相关测试**：[test_knowledge_checks.py:115](../../aearn/services/api/tests/learning/test_knowledge_checks.py#L115)（`test_prediction_ordering_and_code_range_are_strictly_scored`）；[test_tutor_teaching_artifact_commit.py:828](../../aearn/services/api/tests/tutor/test_tutor_teaching_artifact_commit.py#L828)（`test_knowledge_check_receipts_replay_and_evaluation_continuation_are_authoritative`）。
- **边界**：不是所有错误都要求补救；补救/提示后答对非独立；independent_mastery_eligible 不等于已更新 mastery 或 Gate。

### AG-11-003

[对应问题：Review 为什么按有限会话统一结算，而不是每做一道题就更新复习计划？](aearn-agent-design-handbook.md#ag-11-003)

- **核心结论**：ReviewSession 完整终态批次按分数/独立性/关键失败聚合，事务统一写 schedule event、mastery evidence 和 finalization，重复终结重放。
- **实现状态**：当前实现
- **验证状态**：源码与相关测试断言核对；本轮未执行业务测试、provider、数据库或浏览器；核对日期 2026-09-16。
- **源码/规格**：[session_repository.py:714](../../aearn/services/api/app/services/learning/reviews/session_repository.py#L714)（`PostgresReviewSessionRepository.finalize_session`）；[scheduler.py:64](../../aearn/services/api/app/services/learning/reviews/scheduler.py#L64)（`rate_review`）；[scheduler.py:85](../../aearn/services/api/app/services/learning/reviews/scheduler.py#L85)（`advance_schedule`）；[service.py:687](../../aearn/services/api/app/services/learning/reviews/service.py#L687)（`ReviewService.finalize_session`）。
- **相关测试**：[test_review_sessions.py:116](../../aearn/services/api/tests/learning/test_review_sessions.py#L116)（`test_review_session_warmup_attempt_and_exactly_once_finalization`）；[test_review_sessions.py:251](../../aearn/services/api/tests/learning/test_review_sessions.py#L251)（`test_review_batch_waits_for_every_terminal_attempt_before_finalization`）；[test_review_sessions.py:365](../../aearn/services/api/tests/learning/test_review_sessions.py#L365)（`test_candidate_shortage_is_recoverable_without_low_quality_fallback`）。
- **边界**：warmup/单题终态不等于整批结算；不宣称外部模型执行一次、当前队列清空或长期学习效果已测量。

### AG-12-001

[对应问题：如果学习材料或用户消息里出现 Prompt Injection，系统靠什么限制后果？](aearn-agent-design-handbook.md#ag-12-001)

- **核心结论**：不能只在系统提示里写“忽略恶意指令”。Harness 路径会对模型动作做 Skill、capability、effect 和当前策略检查；Sidecar 规划工具另有类型化注册表和状态栅栏。最后都要由领域与持久化逻辑决定是否提交，不能因模型被诱导就授予任意权限；内容层误导仍需单独评估。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[decision_gate.py:54](../../aearn/services/api/app/services/tutor/decision_gate.py#L54)（`CatalogTutorDecisionGate.validate`）；[learning_plan_tools.py:98](../../aearn/services/api/app/agents/runtime/learning_plan_tools.py#L98)（`LearningPlanRuntimeToolRegistry.from_postgres`）；[plan_tools.py:689](../../aearn/services/api/app/services/learning/plan_tools.py#L689)（`LearningPlanToolService._fence_result`）；[context_builder.py:543](../../aearn/services/api/app/agents/harness/context_builder.py#L543)（`_sanitize_source_value`）；[safe_projection.py:126](../../aearn/services/api/app/services/tutor/safe_projection.py#L126)（`TutorSafeProjection`）。
- **相关测试**：[test_tutor_trace_redaction.py:21](../../aearn/services/api/tests/tutor/test_tutor_trace_redaction.py#L21)（`test_safe_projection_removes_nested_fields_and_value_shaped_protected_data`）。
- **边界**：不能声称彻底解决 Prompt Injection，也不能把某个正则、提示词或拒绝案例称为完整安全证明。

### AG-12-002

[对应问题：让学习者运行代码如何隔离？为什么不能说“用了 Docker 就安全”？](aearn-agent-design-handbook.md#ag-12-002)

- **核心结论**：独立容器执行器使用服务端审核的不可变 image lock 构造启动配置，而不是让模型选择镜像、命令或挂载。配置包括无网络、只读根文件系统、非 root、去能力及资源上限。但当前 image-lock 清单为空且默认关闭，因此能讲已实现的隔离机制，不能讲已经提供生产级容器执行服务。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[launch.py:34](../../aearn/services/executor/aearn_executor/launch.py#L34)（`build_launch_spec`）；[service.py:184](../../aearn/services/executor/aearn_executor/service.py#L184)（`ExecutorService._refresh_health`）；[settings.py:48](../../aearn/services/executor/aearn_executor/settings.py#L48)；[image-locks.json:1](../../aearn/infra/executor/image-locks.json#L1)。
- **相关测试**：[test_executor_launch.py:47](../../aearn/services/executor/tests/test_executor_launch.py#L47)（`test_common_launch_profile_is_strict_and_has_no_host_mount_or_network_escape`）；[test_executor_service.py:116](../../aearn/services/executor/tests/test_executor_service.py#L116)（`test_feature_off_executor_records_safe_health_without_constructing_runtime_work`）；[test_executor_service.py:137](../../aearn/services/executor/tests/test_executor_service.py#L137)（`test_enabled_executor_with_empty_lock_registry_never_probes_or_starts_a_runtime`）。
- **边界**：不声称容器已默认可用、通过真实 Docker conformance、支持任意语言，或绝对不存在逃逸风险。

### AG-12-003

[对应问题：怎么在可观测性与隐私之间取舍？日志和流式输出是否一样处理？](aearn-agent-design-handbook.md#ag-12-003)

- **核心结论**：诊断记录应优先保留安全标识、阶段、稳定错误码、版本和计数，而不是复制整份 prompt、模型载荷或代码。Aearn 对诊断做白名单投影和导出时再投影，并用受限结构日志帮助定位。用户可见 Runtime 输出则有独立协议，不能笼统说所有 reasoning 都不显示，也不能把任意原始 payload 当作公开内容。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[safe_projection.py:136](../../aearn/services/api/app/services/tutor/safe_projection.py#L136)（`TutorSafeProjection.project`）；[safe_projection.py:140](../../aearn/services/api/app/services/tutor/safe_projection.py#L140)（`TutorSafeProjection.export`）；[safe_diagnostics.py:45](../../aearn/services/api/app/core/safe_diagnostics.py#L45)（`log_safe_event`）；[useTutorConversationStream.ts:278](../../aearn/apps/desktop/src/hooks/useTutorConversationStream.ts#L278)。
- **相关测试**：[test_safe_diagnostics.py:24](../../aearn/services/api/tests/tutor/test_safe_diagnostics.py#L24)（`test_message_formatter_keeps_fields_and_never_formats_secrets`）；[test_tutor_trace_redaction.py:59](../../aearn/services/api/tests/tutor/test_tutor_trace_redaction.py#L59)（`test_trace_outbox_and_export_never_rehydrate_learner_or_historical_malformed_payload`）；[useTutorConversationStream.test.ts:61](../../aearn/apps/desktop/src/hooks/tests/useTutorConversationStream.test.ts#L61)（`accepts raw Runtime reasoning and final-answer item streams`）。
- **边界**：不宣称所有信息都零泄漏，也不把 diagnostics 白名单等同于所有产品输出通道的统一内容规则。

### AG-13-001

[对应问题：为什么使用 SSE？传输的只是模型 token 吗？](aearn-agent-design-handbook.md#ag-13-001)

- **核心结论**：项目主要是服务端持续推送、客户端通过普通请求提交操作，SSE 适合这种方向。但这里不是裸 token 转发：流中有会话事件身份、序号、游标、Turn 身份和受控输出项。前端用 fetch 读取 text/event-stream，分别处理文本与业务事件；SSE 是传输形式，业务完成仍取决于服务端状态。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[useTutorConversationStream.ts:137](../../aearn/apps/desktop/src/hooks/useTutorConversationStream.ts#L137)；[useTutorConversationStream.ts:258](../../aearn/apps/desktop/src/hooks/useTutorConversationStream.ts#L258)（`toTutorTurnOutputPayload`）；[tutor.py:169](../../aearn/services/api/app/routes/tutor.py#L169)（`stream_conversation_events`）。
- **相关测试**：[useTutorConversationStream.test.ts:61](../../aearn/apps/desktop/src/hooks/tests/useTutorConversationStream.test.ts#L61)（`accepts raw Runtime reasoning and final-answer item streams`）。
- **边界**：不把 SSE 选型等同于可恢复业务协议，也不把输出流的完成当成教学结果完成。

### AG-13-002

[对应问题：网络断开、事件重复或中间丢失时，页面怎样恢复？](aearn-agent-design-handbook.md#ag-13-002)

- **核心结论**：客户端保存不透明游标，重连时通过 Last-Event-ID 发送；服务端按用户和会话读取之后的事件。前端跳过已处理序号，发现序号缺口、非法游标或事件结构错误时要求重新读取权威快照。其余 HTTP/网络错误按重连计数退避；成功建流会清零计数，所以不是整个会话的总重试上限。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[useTutorConversationStream.ts:117](../../aearn/apps/desktop/src/hooks/useTutorConversationStream.ts#L117)；[useTutorConversationStream.ts:173](../../aearn/apps/desktop/src/hooks/useTutorConversationStream.ts#L173)；[public_api.py:516](../../aearn/services/api/app/services/tutor/public_api.py#L516)（`TutorPublicService.replay_conversation_events`）；[public_api.py:482](../../aearn/services/api/app/services/tutor/public_api.py#L482)（`TutorPublicService.read_conversation_snapshot`）；[conversation.py:1097](../../aearn/services/api/app/services/tutor/persistence/conversation.py#L1097)（`ConversationPersistenceMixin.conversation_events_after`）；[TutorConversationSurface.tsx:393](../../aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx#L393)（`requireThinkingSnapshot`）。
- **相关测试**：[useTutorConversationStream.test.ts:110](../../aearn/apps/desktop/src/hooks/tests/useTutorConversationStream.test.ts#L110)（`requires a fresh snapshot for cursor and protocol failures`）；[test_tutor_conversation_runtime.py:157](../../aearn/services/api/tests/tutor/test_tutor_conversation_runtime.py#L157)（`test_conversation_events_are_ordered_idempotent_scoped_and_append_only`）。
- **边界**：不宣称断线从不发生、SSE 消息只送一次，或仅靠客户端序号就完成端到端业务幂等。

### AG-13-003

[对应问题：怎样避免“前端看起来已停止或已通过，但后端其实不是”的假状态？](aearn-agent-design-handbook.md#ag-13-003)

- **核心结论**：停止读流不等于停止后端任务，点击通过也不等于正式进度变化。控制操作必须发给服务端并带预期版本和 Turn 身份；页面在收到权威结果后再刷新。课程进度刷新同时检查用户、课程、知识点和请求 generation，避免旧请求覆盖新页面。
- **实现状态**：当前实现
- **验证状态**：源码核对；进度刷新测试属于前置提交时已通过的 7 文件/133 测试集合，不能外推中断全链路；核对日期 2026-09-16。
- **源码/规格**：[public_api.py:372](../../aearn/services/api/app/services/tutor/public_api.py#L372)（`TutorPublicService.interrupt_turn`）；[TutorConversationSurface.tsx:559](../../aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx#L559)（`runMutation`）；[useTutorConversationStream.ts:113](../../aearn/apps/desktop/src/hooks/useTutorConversationStream.ts#L113)；[TrackLearningWorkspace.tsx:175](../../aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx#L175)（`refreshRouteSummary`）；[TrackLearningWorkspace.tsx:293](../../aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx#L293)（`handleLessonProgressChange`）。
- **相关测试**：[LearningWorkspaceProgressRefresh.test.tsx:97](../../aearn/apps/desktop/src/features/learning/tests/LearningWorkspaceProgressRefresh.test.tsx#L97)（`refetches route summary after a projected terminal Attempt and keeps the completed lesson selected`）；[LearningWorkspaceProgressRefresh.test.tsx:114](../../aearn/apps/desktop/src/features/learning/tests/LearningWorkspaceProgressRefresh.test.tsx#L114)（`does not optimistically advance the route for a failed terminal Attempt`）。
- **边界**：当前测试集合包含 fixture；不能据此宣称真实 provider 的中断、并发控制与所有端到端进度都已实测通过。

### AG-14-001

[对应问题：如何测试 Agent？为什么“几个问题回答得不错”还不够？](aearn-agent-design-handbook.md#ag-14-001)

- **核心结论**：Tutor eval 使用确定性场景核对 catalog/Skill hash、策略拒绝、严格协议、有界循环、过期 effect、模型不可用与脱敏；fixture 结果不是实测模型正确率。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[evals.py:75](../../aearn/services/api/app/services/tutor/evals.py#L75)（`load_tutor_eval_cases`）；[evals.py:112](../../aearn/services/api/app/services/tutor/evals.py#L112)（`run_tutor_eval_case`）；[evals.py:152](../../aearn/services/api/app/services/tutor/evals.py#L152)（`_assert_catalog_identity`）；[acceptance-test-plan.md:1](../qa/acceptance-test-plan.md#L1)。
- **相关测试**：[test_tutor_evals.py:34](../../aearn/services/api/tests/tutor/test_tutor_evals.py#L34)（`test_fake_only_tutor_eval_fixture_covers_pinned_catalog_and_required_scenarios`）；[test_tutor_adaptive_teaching_evals.py:34](../../aearn/services/api/tests/tutor/test_tutor_adaptive_teaching_evals.py#L34)（`test_gate_completion_admits_exactly_one_progress_turn_and_frozen_summary`）。
- **边界**：不把 fixture 通过率写成真实模型质量，不把绿色构建写成发布批准，也不捏造端到端成功率。

### AG-14-002

[对应问题：怎样证明上下文策略改善了效果，而不只是减少了 token？](aearn-agent-design-handbook.md#ag-14-002)

- **核心结论**：TutorContextEvalReceipt 区分估算、可空 usage 和事实覆盖指标；离线 runner 调用 _FixtureJsonClient，调用次数、usage 与延迟来自假客户端或 fixture，而非真实模型测量。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[context_evals.py:117](../../aearn/services/api/app/services/tutor/context_evals.py#L117)（`TutorContextEvalReceipt`）；[context_evals.py:349](../../aearn/services/api/app/services/tutor/context_evals.py#L349)（`run_tutor_context_eval_case`）；[context_evals.py:436](../../aearn/services/api/app/services/tutor/context_evals.py#L436)（`_selection_receipt`）；[context_evals.py:376](../../aearn/services/api/app/services/tutor/context_evals.py#L376)（`build_tutor_context_calibration_report`）。
- **相关测试**：[test_tutor_evals.py:102](../../aearn/services/api/tests/tutor/test_tutor_evals.py#L102)（`test_context_eval_receipts_are_safe_and_keep_attempt_usage_separate`）；[test_tutor_evals.py:138](../../aearn/services/api/tests/tutor/test_tutor_evals.py#L138)（`test_calibration_report_groups_versioned_safe_metrics_and_applies_sample_threshold`）。
- **边界**：字段和评估函数存在不等于所有指标已实际采集，更不等于已有性能、成本或教学收益提升数字。

### AG-14-003

[对应问题：真实调用失败时，你怎么定位，而不是不停改 Prompt 或重试？](aearn-agent-design-handbook.md#ag-14-003)

- **核心结论**：安全日志记录有界阶段、错误码、版本及关联标识；Worker 在派发失败后以 owner 和 lease generation 更新重试状态，不将原始异常文本作为公开错误。
- **实现状态**：当前实现
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[safe_diagnostics.py:15](../../aearn/services/api/app/core/safe_diagnostics.py#L15)；[safe_diagnostics.py:45](../../aearn/services/api/app/core/safe_diagnostics.py#L45)（`log_safe_event`）；[interactive_worker.py:88](../../aearn/services/api/app/services/tutor/interactive_worker.py#L88)；[evals.py:112](../../aearn/services/api/app/services/tutor/evals.py#L112)（`run_tutor_eval_case`）。
- **相关测试**：[test_safe_diagnostics.py:124](../../aearn/services/api/tests/tutor/test_safe_diagnostics.py#L124)（`test_dispatch_logs_exception_before_retry_write_can_fail`）。
- **边界**：本章是基于现有诊断机制的方法论，不声称本轮运行了新的真实 provider、数据库或完整故障恢复测试。

### AG-15-001

[对应问题：怎样控制模型调用成本，为什么 max_model_calls 不是账单请求数？](aearn-agent-design-handbook.md#ag-15-001)

- **核心结论**：逻辑决策预算、两次 provider 决策尝试、最多三次底层可重试 HTTP 尝试与 Sidecar 零传输重试属于不同层，须分层测量成本。
- **实现状态**：当前实现；规划/建议（成本测量）
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[run_loop.py:90](../../aearn/services/api/app/services/tutor/run_loop.py#L90)（`TutorRunLoop.run`）；[provider_gateway.py:67](../../aearn/services/api/app/services/tutor/provider_gateway.py#L67)（`PRIMARY_PROVIDER_DECISION_ATTEMPTS`）；[llm_client.py:29](../../aearn/services/api/app/services/llm/llm_client.py#L29)（`LLM_PROVIDER_RETRY_ATTEMPTS`）；[llm_client.py:725](../../aearn/services/api/app/services/llm/llm_client.py#L725)（`_request_with_retries`）；[codex_config.py:135](../../aearn/services/api/app/agents/runtime/codex_config.py#L135)（`ensure_codex_runtime_home`）；[learning_plan_tools.py:45](../../aearn/services/api/app/agents/runtime/learning_plan_tools.py#L45)（`LearningPlanToolBudget`）。
- **相关测试**：[test_tutor_provider_gateway.py:1404](../../aearn/services/api/tests/tutor/test_tutor_provider_gateway.py#L1404)；[test_tutor_provider_gateway.py:865](../../aearn/services/api/tests/tutor/test_tutor_provider_gateway.py#L865)；[test_codex_learning_plan_tools.py:485](../../aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools.py#L485)。
- **边界**：不能提供未测量的平均费用、降本比例或总吞吐；不得用逻辑 model_call_count 冒充 HTTP 次数或完整账单计数。

### AG-15-002

[对应问题：流式输出越快越好吗？怎样处理慢消费者、失控工具和取消后的残留执行？](aearn-agent-design-handbook.md#ag-15-002)

- **核心结论**：当前 Sidecar 通过有界队列、多维预算与终止确认/受控 shutdown 收敛资源风险；性能收益尚无本轮实测。
- **实现状态**：当前实现；规划/建议（性能测量）
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[codex_adapter.py:141](../../aearn/services/api/app/agents/runtime/codex_adapter.py#L141)（`CodexAppServerRuntime.run_turn`）；[codex_adapter.py:542](../../aearn/services/api/app/agents/runtime/codex_adapter.py#L542)（`CodexAppServerRuntime._publish_event`）；[codex_adapter.py:468](../../aearn/services/api/app/agents/runtime/codex_adapter.py#L468)（`CodexAppServerRuntime._stop_turn`）；[learning_plan_tools.py:45](../../aearn/services/api/app/agents/runtime/learning_plan_tools.py#L45)（`LearningPlanToolBudget`）；[learning_plan_tools.py:235](../../aearn/services/api/app/agents/runtime/learning_plan_tools.py#L235)（`LearningPlanRuntimeToolRegistry.invoke`）；[codex_dispatcher.py:176](../../aearn/services/api/app/services/tutor/codex_dispatcher.py#L176)（`CodexTutorRunDispatcher.dispatch`）。
- **相关测试**：[test_planning_runtime_limits.py:219](../../aearn/services/api/tests/codex_sidecar/test_planning_runtime_limits.py#L219)；[test_planning_runtime_limits.py:244](../../aearn/services/api/tests/codex_sidecar/test_planning_runtime_limits.py#L244)；[test_planning_runtime_limits.py:341](../../aearn/services/api/tests/codex_sidecar/test_planning_runtime_limits.py#L341)。
- **边界**：不把流式首字等同业务成功；不宣称已有吞吐、尾延迟或多租户隔离压测结论；ACK 不等于远端终止。

### AG-15-003

[对应问题：没有性能数据时，怎样提出可信的优化与框架演进计划？](aearn-agent-design-handbook.md#ag-15-003)

- **核心结论**：现有循环与预算遥测可作为测量入口，但完整计费覆盖及跨框架性能收益尚未验证；演进应先保持领域契约等价。
- **实现状态**：当前实现（测量入口）；规划/建议（演进方案）
- **验证状态**：源码核对；相关测试文件存在，本轮未执行；核对日期 2026-09-16。
- **源码/规格**：[run_loop.py:90](../../aearn/services/api/app/services/tutor/run_loop.py#L90)（`TutorRunLoop.run`）；[provider_gateway.py:173](../../aearn/services/api/app/services/tutor/provider_gateway.py#L173)（`PrimaryTutorProviderGateway.decide`）；[codex_adapter.py:141](../../aearn/services/api/app/agents/runtime/codex_adapter.py#L141)（`CodexAppServerRuntime.run_turn`）；[runtime_selection.py:171](../../aearn/services/api/app/services/tutor/runtime_selection.py#L171)（`TutorRuntimeSelectionPolicy.select`）；[plan_service.py:214](../../aearn/services/api/app/services/learning/plan_service.py#L214)（`LearningPlanSessionService._confirm_session`）。
- **相关测试**：[test_tutor_run_loop.py:685](../../aearn/services/api/tests/tutor/test_tutor_run_loop.py#L685)；[test_planning_runtime_limits.py:352](../../aearn/services/api/tests/codex_sidecar/test_planning_runtime_limits.py#L352)；[test_learning_plan_sessions.py:339](../../aearn/services/api/tests/learning/test_learning_plan_sessions.py#L339)。
- **边界**：本题为建议，不含已完成压测、上线收益、迁移排期或未经确认的个人贡献；真实 provider/DB 验证需主会话另行授权。

## 外部官方资料

外部资料用于解释框架或标准的通用能力，不能证明 Aearn 已采用全部能力。均于 2026-09-16 核对；日期是本轮访问日期，不是发布日期。搜索工具没有返回可用正文时，改为直接只读读取官方页面或 Markdown 正文；未调用模型服务。

| 来源 | 支持的范围 |
| --- | --- |
| [F-01 Agents SDK](https://developers.openai.com/api/docs/guides/agents/sdk) | 提供代码优先的 Agent 接入、模型与工具、编排、护栏、状态及观测的入口。 |
| [F-02 Running agents](https://developers.openai.com/api/docs/guides/agents/running-agents) | runner 围绕模型和工具组织执行；可通过应用存储及 SDK session 维护历史和恢复状态。 |
| [F-03 Guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals) | 区分输入、输出、工具检查与人工审批；阻断式和并行检查的执行时机不同。 |
| [F-04 Results and state](https://developers.openai.com/api/docs/guides/agents/results) | 运行结果可包含最终输出、后续历史、待审批 interruption 和可恢复 state；暂停运行不一定有最终答案。 |
| [F-05 Function calling](https://developers.openai.com/api/docs/guides/function-calling) | 模型提出应用函数调用请求，应用执行工具并把结果回传；函数 schema 是工具接口描述。 |
| [F-06 Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs) | 区分 JSON 有效性与 schema 遵从；结构化回复和函数调用面向不同接口用途。 |
| [F-07 Codex App Server](https://learn.chatgpt.com/docs/app-server) | App Server 面向产品客户端集成，提供双向 JSON-RPC、thread/turn 生命周期、流式事件与审批等接口。 |
| [F-08 Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | checkpointer 持久化线程图状态；store 管理跨线程应用数据。应区分内存保存器与持久化后端。 |
| [F-09 Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | interrupt 可暂停图并等待外部输入，结合 checkpointer、thread_id 与恢复输入继续执行。 |
| [F-10 Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) | 线程 checkpoint 保存图状态，可用于继续执行与故障恢复；节点写入和完整 checkpoint 的边界不同。 |
| [Anthropic — Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | 工作流与 Agent 自主性的概念区分，不作为 Aearn 架构事实来源 |
| [WHATWG — Server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html) | SSE 与 Last-Event-ID 标准语义；项目使用 fetch 自行实现读取和恢复 |

## 不应在面试中声称的事项

1. 没有证据就不声称上线规模、性能提升、成本下降、长期学习收益或全部由个人独立实现。
2. 不把旧 Graph/SDK、未接入工具、默认关闭功能和规划中的 RAG 能力当作当前完整实现。
3. 不把模型窗口当实际输入量，不把单次逻辑决策当 HTTP 请求数，也不把估算 token 当真实账单。
4. 不把结构化 JSON、202 受理、模型结束、Artifact 存在、评分、Gate 进度和 UI 展示混成一个成功指标。
5. 不说 exactly-once 模型执行、注入绝对免疫或容器绝对安全；具体业务去重和权限边界要具体说明。
6. 不把前端禁用按钮、断开流或显示成功当成服务端幂等、真实中断或正式进度证明。
7. 不将本轮文档交付解释为发布、部署或推送授权。
