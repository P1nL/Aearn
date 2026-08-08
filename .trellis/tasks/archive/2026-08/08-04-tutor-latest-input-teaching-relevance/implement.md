# Tutor 最新输入与教学相关性实施计划

## 开始前置条件

- 在用户审阅规划工件并明确批准实施之前，本任务保持 `planning` 状态。
- 代码编辑前重新运行 `git status --short --branch`，并检查所有重叠 diff。保留用户当前已有的全部修改；不得 reset、restore、clean 或大范围 stage 工作树。
- 编辑前加载 `trellis-before-dev`、后端规范索引、相关 Harness/provider/context 规范和当前运行时 source of truth。
- 不得 commit、push、deploy、修改生产数据，也不得读取/打印凭据。

## 有序实施清单

### 1. 固化当前输入 Contract

- 在 Harness 上下文 contract 中增加独立、有界的当前输入表示，并与可选的近期历史分离。
- 定义允许的交互式/主动式 shape、来源身份、清理、token 记账、metadata 和类型化失败行为。
- 保持 contract 与 provider 无关，避免按短语、语言或主题进行分支。

**风险 / 回滚：** Contract 变更会影响大量 fake 和测试。原子更新 contract consumer，并且只为主动式上下文保留窄范围兼容默认值；绝不能将交互式当前输入默认回退为陈旧历史。

### 2. 在 PostgreSQL 上下文加载中解析精确当前输入

- 在 `PostgresTutorContextLoader` 中，通过活动 `run_id` 和精确 `input_revision` 查询 `tutor_run_input_events`，关联规范学习者消息，并限定到对应对话，以解析当前学习者消息。
- 对证据缺失、重复、角色错误、跨对话或不匹配情况，以类型化内部 context error 拒绝处理。
- 从可选历史中排除精确的当前消息 ID。
- 选择最新既往消息，并按 builder contract 要求的顺序提供。
- 添加聚焦的数据库支持测试，覆盖首轮、普通新鲜 TurnRun、显式 continuation revision、长历史、相同时间戳和不匹配失败。

**风险 / 回滚：** 不得通过 `created_at`、消息角色或最后一条对话记录推断当前输入。无需 schema 变更或数据重写。

### 3. 显式处理必需输入的 Budget

- 重构 `TutorContextBuilder`，先为当前输入预留空间并输出，再允许可选上下文消耗 budget。
- 保持可选 section 上限、清理、脱敏、hash、high-water metadata 和 compaction 行为确定不变。
- 修正近期历史选择，使最新的有界既往消息得以保留，并按时间顺序呈现。
- 实现并测试确定性的当前输入超 budget 处理。如果最小安全表示也无法容纳，则在 provider 调用前返回类型化失败。
- 更新内存上下文，以及 context-builder/eval fixture。

**风险 / 回滚：** 禁止只增加 `RECENT_MESSAGES` 或 token 上限，因为这会使 invariant 在更长对话中继续失效。

### 4. 强化 Provider 教学策略

- 重构 `_build_messages()`，使 provider payload 将 `current_input` 与辅助上下文明显分开。
- 在 system instruction 中加入简洁的最新意图、纠正、打断、完成、先回答、最多一次追问和不得继续陈旧路径规则。
- 与唯一允许的 repair retry 共享该策略，确保 schema 修复不会丢失教学行为。
- 保持精确 JSON shape、安全检查、标题规则、continuation 规则、model/protocol 选择、timeout/output 边界和无 fallback 行为。
- 添加测试，检查实际初始消息和 repair 消息，并确保原始受保护内容不被泄露。

**风险 / 回滚：** 不得增加硬编码响应或关键字路由。Prompt 行为是由上下文保证和 eval 证据支持的模型 instruction contract，而不是第二套确定性 Tutor 实现。

### 5. 添加回归与评估证据

- 将报告中的对话转换为确定性的 loader/builder/provider 回归 fixture。
- 仅在当前输入固定、最新历史选择、策略存在性和 provider 未被调用的失败行为所需范围内，扩展现有 Tutor eval runner 和 fixture schema。
- 使用 `design.md` 中的有界 rubric，添加一个明确的可选真实 provider smoke 命令/场景，并安全捕获输出。
- 普通测试保持离线且确定性；除非明确启用并完成配置，否则跳过 live smoke。

**风险 / 回滚：** Fake eval 证明的是 contract，而不是真实模型质量。文档和报告必须保留这一区分。

### 6. 更新 Source-of-Truth 文档与可复用规范

- 仅在实现和测试证明最终行为后，更新 `docs/architecture/tutor-harness-runtime.md`。
- 如果实现确认了“权威当前输入是强制项，且可选历史不得挤掉它”，则增加该可复用后端规则。
- 不得恢复已归档的 Graph/onboarding 代码，也不得创建重复产品规格。

### 7. 质量审查与工作树审计

- 检查完整 diff，关注当前输入重复、时间戳推断、可选上下文优先于必需输入、原始文本泄露、public API/SSE shape 变更、主动式运行回归和意外 provider fallback。
- 确认只有预期文件被修改，且原有未提交修改保持完整。
- 所有编辑完成后运行 `git diff --check`。

## 预期实施范围

可能涉及以下文件，但编辑前必须重新检查：

- `aearn/services/api/app/agents/harness/contracts.py`
- `aearn/services/api/app/agents/harness/context_builder.py`
- `aearn/services/api/app/services/tutor/interactive.py`
- `aearn/services/api/app/services/tutor/provider_gateway.py`
- 仅当缺少类型化 context-failure 映射时，修改 `aearn/services/api/app/services/tutor/run_loop.py`
- `aearn/services/api/app/services/tutor/evals.py`
- `aearn/services/api/tests/test_tutor_context_builder.py`
- `aearn/services/api/tests/test_tutor_provider_gateway.py`
- 相关的 interactive/persistence integration 测试
- `aearn/services/api/tests/test_tutor_evals.py`
- `aearn/services/api/tests/fixtures/tutor_evals/`
- `docs/architecture/tutor-harness-runtime.md`
- 确认存在可复用 contract 时，修改 `.trellis/spec/backend/quality-guidelines.md`

## 必需验证

先运行聚焦检查；数据库支持的命令应串行运行：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_context_builder.py tests/test_tutor_provider_gateway.py tests/test_tutor_evals.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_input_merge.py tests/test_tutor_run_loop.py tests/test_tutor_sse.py -q
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-tutor-latest-input-teaching-relevance
git diff --check
```

如果可选真实 provider smoke 已获批准并完成配置，则在确定性检查之后运行其明确命令。只记录对学习者安全的输出和 rubric boolean；不得存储 secret、原始 prompt、reasoning 或 provider payload。

## 执行 `task.py start` 前的审查门

- 可见的纠正确认决策已记录在 `prd.md`：简短确认、停止陈旧路径、回答当前输入，并且最多询问一个必要的后续问题。
- 记录该决策后验证任务目录。
- 展示最终计划，并单独请求实施批准。任务创建和产品行为批准不等于实施批准。
