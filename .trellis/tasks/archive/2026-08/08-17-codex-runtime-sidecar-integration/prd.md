# Codex Runtime Sidecar 集成

## 目标与用户价值

在不 Fork、不侵入修改 `openai/codex` Core 的前提下，把 Codex App Server 作为 Aearn 可替换的 Agent Runtime Sidecar：Codex 负责 thread/turn/item、模型调用、工具循环、错误反馈与恢复；Aearn 继续拥有学习领域、数据库、用户作用域、公开 API、Desktop UI 和所有持久化业务 authority。

用户价值包括：

1. 模型工具参数或草案结构错误可以在同一 Turn 内被反馈和修复，不再要求学习者重复输入。
2. 工具失败、Runtime 失败和最终失败都成为显式、可恢复、可审计的 Turn/item，不再出现“回复被吃”。
3. Aearn 保留已经完成的 LearningPlan、LearningTrack、Lesson、Exercise、mastery、Queue、SSE 和确认事务，不把产品重写成 Codex Fork。
4. Codex 上游可以独立升级或回滚，Aearn 业务代码不直接依赖其 wire DTO。

## 背景与已确认事实

1. Aearn 当前正式运行时是 Tutor Harness，`TutorInteractiveWorker -> TutorRunDispatcher -> TutorRunLoop` 是当前交互式执行组合根。
2. 当前 Provider 使用一个严格 envelope 同时承载 learner-visible message 与 action；action 无效可能阻止 message 成为公开 item。
3. 当前 Capability 非 `completed` 时直接终止为 `BLOCKED_POLICY / capability_denied`；这会把模型可修复的领域输入错误提升为 Turn 终态。
4. 当前学习计划 Capability 使用 `profile_json` 与 `module_N` JSON 字符串，存在双层 JSON、重复事实和 360 字符限制。
5. Aearn 已经具有 `message | process | elicitation | approval | error` 公开 item union，以及 `in_progress | completed | interrupted | failed` Turn 状态；Desktop 无需直接消费 Codex DTO。
6. `openai/codex@c6058ccaa91ab17159cf805bf4d6d4edd87fe5fc` 的 App Server 提供 stdio JSON-RPC、thread/turn/item、dynamic tools、interrupt/steer、明确 failed turn 与账户接口。
7. `dynamicTools` 当前为 experimental；WebSocket transport 也明确不用于生产。Windows 本机不支持 app-server daemon lifecycle，因此目标实现必须由一个受控进程拥有 stdio child。
8. 本机 Codex 可执行文件是 `codex-cli 0.142.0-cometix`，与开源 main revision 不同；实施必须执行 protocol/version/capability preflight，不能只检查命令存在。
9. `08-15-tutor-public-thinking-text-stream` 与 `08-16-tutor-plan-confirmation-entry` 已于 2026-08-17 归档；当前无产品业务代码修改，`.trellis/tasks/.obsidian/workspace.json` 的本地 UI 状态变化不属于本任务交付。
10. 已归档的 `08-11-codex-aearn-agent-architecture-comparison` 是差距证据，本任务不重复全面评分，而是完成可运行集成。

## 已确认产品与架构决策

1. **不 Fork Codex。** 所有 Aearn 变更位于 Aearn 仓库，Codex 以外部 Runtime 运行。
2. **父任务只承载规划与最终集成门。** 实际工作由六个可独立验证的 child 完成，父任务不直接 `task.py start`。
3. **先验证后切换。** 第一个 child 是隔离协议 spike；只有 Go 条件满足才继续正式 Adapter。
4. **替换 Dispatcher，不嵌套双重 Loop。** Codex 路径实现新的 `TutorRunDispatcher`，不把 Codex 塞入 `TutorProviderGateway`，也不让 `TutorRunLoop` 再包 Codex loop。
5. **Aearn ID 和数据库始终权威。** Codex thread/turn/item id 只是受控 correlation，不替代 Aearn conversation/run/item id。
6. **首个正式切换范围仅限新建 `plan_drafting`。** existing conversation、非计划 Tutor、proactive、Lesson/Exercise/Review 继续使用 `harness_v1`。
7. **Runtime 创建时冻结。** 每个 run 的 `runtime_kind` 创建后不可变；Retry 沿用同一 runtime root，不在已产生副作用后跨 Runtime fallback。
8. **Typed domain tools。** 首条计划链路使用结构化 `modules[]`，profile 从 server-authoritative planning facts 构造。
9. **Dynamic tools 仅在版本固定和 capability preflight 下使用。** Adapter 保留未来迁移 MCP 的工具注册端口。
10. **本地 MVP 不分发 Codex。** 使用 operator 安装的兼容 Codex binary 和隔离 Aearn Codex Home；安装器、品牌、商业分发与生产部署属于范围外。
11. **公共安全投影保持 Aearn 契约。** reasoning、raw arguments、prompt、provider body、command/path 和 secret 不进入 API/SSE/Desktop。
12. **DeepSeek 是正式兼容性门。** 用户于 2026-08-18 确认：精确模型 `deepseek-v4-flash` + Responses 必须通过 Child 1 的真实 tool-repair smoke；OpenAI 模型、其他 DeepSeek 模型、Chat Completions 或任何 provider/model/protocol fallback 都不能替代 Go 证据。

## 子任务地图与依赖

| 顺序 | 子任务 | 交付物 | 依赖 |
| --- | --- | --- | --- |
| 1 | `08-17-codex-sidecar-protocol-spike` | Windows stdio、`deepseek-v4-flash` Responses、dynamic tool、同 Turn 修复与 interrupt 的 Go/No-Go 证据 | 无 |
| 2 | `08-17-codex-runtime-adapter-supervisor` | `AgentRuntimePort`、Codex Adapter、独立 worker、stdio 进程监管 | Child 1 = Go |
| 3 | `08-17-codex-learning-plan-tools-recovery` | typed planning tools、server-owned profile、repairable tool result 与预算 | Child 2 |
| 4 | `08-17-codex-tutor-durable-projection` | runtime correlation、safe receipts、Aearn public item/turn 投影 | Child 2、3 |
| 5 | `08-17-codex-plan-drafting-cutover` | 新 plan-drafting scope 的 feature-gated Runtime 选择与控制流接线 | Child 4 |
| 6 | `08-17-codex-sidecar-integration-qa-docs` | 全链路失败矩阵、真实 smoke、回滚演练、source-of-truth 文档 | Child 1-5 |

父子目录结构只表达工作分解。实际依赖以每个 child 的 `prd.md` 和 `implement.md` 为准。

## 范围内

### R1：Runtime Adapter 与进程边界

- 定义 Aearn 自有 `AgentRuntimePort`、Runtime event 和 tool callback contract。
- 用 Python 通过 stdio 管理 `codex app-server --strict-config`。
- 提供 initialize/version/auth/capability preflight、request correlation、事件消费、turn steer/interrupt、timeout、shutdown 与 child crash 收口。
- Child 1 必须使用隔离 custom provider 精确验证 `deepseek-v4-flash` + Responses；后续 Adapter 继承其已验证配置边界。
- 使用独立 `tutor-codex` worker，确保一个进程持有 app-server connection 和 active thread writer ownership。

### R2：Aearn typed learning tools

- `aearn_planning_context_read` 返回 bounded authoritative planning state。
- `aearn_learning_plan_draft` 接收结构化 modules，服务端构造 profile、校验并 append draft。
- 工具结果区分 `completed | repairable_invalid | awaiting_user | conflict | policy_blocked | unavailable | fatal`。
- repairable result 作为正常 tool output 回灌模型；fatal/policy 才终止。

### R3：持久化与公开投影

- Additive 保存 run runtime kind、Codex correlation、Runtime item safe receipts 和 upstream version。
- Codex final agent message 经 Aearn safety、lease、revision 与 ownership gate 后写入 `tutor_messages`。
- failed/interrupted turn 总是写入明确 public turn/process/error 投影。
- reasoning/raw event 不进入 Aearn public surface。

### R4：受控切换

- 新 plan-drafting run 由 server-side feature/cutover policy 选择 `codex_sidecar_v1`。
- existing run 与其他 scope 不迁移、不双写。
- Queue、Steer、Interrupt、Retry、LearningPlan confirm、SSE 和 Desktop contract 保持服务端权威。
- Sidecar 不健康时阻止新 Codex run admission；active run 不静默换 Runtime。

### R5：验证与治理

- fake app-server fixture、协议 contract tests、领域工具测试、DB/Persistence tests、Desktop tests 和 opt-in real Codex smoke。
- 版本兼容矩阵、启动/关闭、健康检查、认证、超时、崩溃、回滚和数据保留文档。
- 任何真实 provider 调用、安装、发布、生产切换都继续需要单独授权。

## 范围外

- Fork、修改或提交 `openai/codex` 源码。
- 将 Aearn 领域类写入 `codex-rs/core`。
- 一次性替换全部 Tutor、proactive、Lesson、Exercise、Review 或 executor。
- 让 Desktop 直接连接 Codex App Server。
- WebSocket transport、Windows daemon 或未经验证的 remote control。
- 将其他 DeepSeek Chat Completions 模型纳入首个 Sidecar cutover，或以 OpenAI/其他模型结果替代 DeepSeek 验收。
- 将全局 `C:\Users\PINKING\.codex` 作为正式 Aearn 可写状态根。
- 捆绑/分发 Codex binary、OpenAI 品牌、账户或托管服务。
- 生产部署、生产数据迁移、Git push。

## 跨任务验收标准

- [x] Child 1 经单独授权完成真实 `deepseek-v4-flash` Responses tool-repair smoke并给出可复现的 Go；未授权/未执行为 pending，DeepSeek No-Go 时父任务停止且不创建半成品正式 cutover。
- [x] Aearn 业务层只依赖 `AgentRuntimePort`，不导入 Codex wire-generated DTO。
- [x] Windows 上只有一个受控 worker process 持有 app-server stdio 与 active thread writer ownership。
- [x] 学习计划工具不再要求模型提供 `profile_json` 或 `module_N` JSON 字符串。
- [x] 一次 repairable 草案错误可在同 Turn 内修复成功，学习者无需重复输入。
- [x] 超预算、policy、安全、stale revision、interrupt 与 Runtime crash 各自有不同终态和安全诊断。
- [x] action/tool 失败不会删除已批准的 learner-visible item；不可恢复失败始终显示 public error。
- [x] 新 plan-drafting 可以 feature-gated 使用 Codex，existing/其他 scope 继续 Harness，且不存在隐式双写或跨 Runtime fallback。
- [x] LearningPlan append-only draft、右侧确认和 LearningTrack 创建 authority 不改变。
- [x] raw reasoning、prompt、tool arguments、provider body、secret、command 和不必要路径不会进入 DB public columns、SSE、API、Desktop 或测试快照。
- [x] 后端 lint/typecheck/tests、Desktop tests/check、DB bootstrap、Trellis validate、`git diff --check` 和回滚演练通过。

## 风险与约束

- Codex App Server 与 dynamic tools 仍可能变化，必须固定版本并 fail closed。
- 本机 Codex 为自定义版本，不能代表官方 main；Child 1 必须同时验证本机目标版本、固定公开协议和 `deepseek-v4-flash` Responses兼容性。
- Codex 对 Chat Completions 的支持已进入弃用路径，因此正式 DeepSeek Sidecar 不得建立在其他 DeepSeek Chat Completions模型上。
- Aearn 当前公开思考流有更严格安全语义；Codex reasoning 不可直接复用，commentary 映射若无法证明安全则保持静态 Think。
- Codex Home、认证和 provider 配置是本地敏感边界；任务工件和日志只记录布尔 readiness、版本和安全错误码。
- 父任务跨度大，必须 child-by-child 实施和验收，不能一次性大重构。
