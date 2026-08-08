# Tutor Provider Usage 与缓存计量

## 目标

为 Tutor 的每个实际 provider attempt 建立统一、安全、可持久化的 token usage contract，准确区分输入、缓存读取、非缓存输入、输出和总量，为物理上下文核算、自适应预算校准、延迟/成本分析和回归评估提供可信数据。

## 依赖

- 父任务：`08-04-tutor-context-governance-adaptive-budget`。
- 实施前依赖 `08-04-tutor-latest-input-teaching-relevance` 完成或至少冻结最终 provider payload/current-input contract，避免 usage receipt 绑定到即将变化的调用边界。
- 本任务完成后，`08-04-tutor-adaptive-context-budget-planner` 才能用真实 receipt 校准估算误差。

## 已确认事实

1. `LLMJsonResponse` 当前只有 `content` 和 `model`，provider usage 在 Responses/Chat Completions 适配后被丢弃。
2. `PrimaryTutorProviderGateway.decide()` 最多进行两个实际 provider attempt：首次请求和一次同 provider repair；现有 `model_call_count` 只在 run loop 的 decision 边界增加一次，不能代表真实 HTTP attempt 数。
3. provider 返回的 `input_tokens` 通常已经包含 `cached_tokens`；正确的非缓存输入是 `input_tokens - cached_tokens`，不能再次把缓存 token 加到总输入。
4. 部分 provider、失败响应或兼容端点可能缺失 usage；系统不得伪造数字，也不得因为 usage 缺失使 Tutor 主流程失败。
5. 当前安全 trace/outbox contract 只允许小型稳定 metadata，不允许 raw provider body、prompt、history、reasoning 或 credential。

## 需求

### U1 — 统一 Usage Contract

- 增加 provider-neutral 的 immutable usage 数据结构，至少支持：
  - `input_tokens`
  - `cached_input_tokens`
  - 派生 `uncached_input_tokens`
  - `output_tokens`
  - `total_tokens`
  - provider 明确提供时的 `reasoning_tokens`
  - `usage_available` 或等价缺失语义
- 所有数值必须非负；存在缓存明细时满足 `cached_input_tokens <= input_tokens`。
- 不强制所有 provider 的 `total_tokens` 严格等于输入加输出；保留 provider reported total，并另行计算规范化派生值用于校验。

### U2 — 每个实际 Attempt 独立

- 每个实际 provider 请求拥有稳定 attempt identity，至少绑定 `run_id`、`input_revision`、run-loop decision iteration 和 gateway attempt index。
- 首次响应被拒绝并 repair 成功时，两个 attempt 分别记录；不能只保留最终成功请求。
- 如果 provider envelope 已返回且 usage 可解析，即使内容/decision 后续校验失败，也应保留该 attempt 的安全 usage receipt。
- transport 在取得 provider envelope 前失败时，不伪造 usage；只保留现有安全错误分类。

### U3 — 多协议解析

- 支持当前 OpenAI-compatible Responses、精确 DeepSeek V4 Flash Responses 和 DeepSeek Chat Completions 路径。
- 解析逻辑必须兼容 provider 把 usage 放在顶层、nested response 或 completion envelope 的现有形态；未知结构返回 usage unavailable。
- Responses stream 必须在 `response.completed` envelope 中保留 usage，不因只提取可见文本而丢弃。

### U4 — 安全持久化

- 使用新增 immutable usage receipt 表或等价 scoped durable contract；不得把 receipt 塞入公开 message/history。
- 记录范围仅限安全标识、provider/model/protocol 枚举或受限字符串、token 数、attempt 状态、时间戳和必要 hash。
- 必须具备 user/run/input revision scope、幂等 identity 和重复写冲突检测。
- 不持久化请求内容、原始响应、prompt、history、reasoning 文本、provider error body、URL、header 或 credential。

### U5 — 调用链传播

- `OpenAICompatibleClient`、`PrimaryTutorProviderGateway`、`TutorProviderResult` 和 lifecycle persistence 原子传播 attempt receipt。
- 不改变 `model_call_count` 的既有 decision-boundary 语义；另行暴露/记录 actual provider attempt count。
- usage 持久化失败应按内部 lifecycle 冲突安全处理，不允许公开半真半假的 token 数。

### U6 — 测试与文档

- 使用固定 provider envelopes 覆盖 cached/uncached、无缓存、usage 缺失、repair 两次请求、invalid decision 和 transport failure。
- 更新运行时、数据库和 QA 文档，明确缓存 token 计入物理输入以及官方 usage 字段的归一化语义。

## 验收标准

- [ ] 一个 `input_tokens=175420`、`cached_input_tokens=170368` 的 receipt 派生 `uncached_input_tokens=5052`，不会得到 `345788` 的错误总输入。
- [ ] 同一次 gateway decision 发生 repair 时，可以审计两个实际 attempt，而 run-level `model_call_count` 仍保持既有语义。
- [ ] Responses 和 Chat Completions fixture 都能解析已提供的 usage；缺失 usage 时返回明确 unavailable，而不是零值伪装。
- [ ] 内容或严格 JSON 校验失败但 envelope usage 可用时，usage receipt 仍可保存；transport 无 envelope 时不伪造 usage。
- [ ] 持久化记录不包含 prompt、raw history、provider body、reasoning、header、URL 或 credential。
- [ ] usage 数据按 user/run/revision/attempt 幂等隔离，跨用户读取或写入被拒绝。
- [ ] 现有 primary-only、same-provider repair、`MODEL_UNAVAILABLE` 和安全日志测试继续通过。
- [ ] 聚焦测试、数据库/bootstrap 测试、Ruff、Mypy、任务验证和 `git diff --check` 通过。

## 范围外

- 根据实时供应商价格计算账单或展示收费 UI。
- 为缓存命中主动改变 provider routing、model 或 protocol。
- 把 usage 缺失视为 provider failure。
- 记录或公开 raw provider response、prompt、reasoning 或 credential。
- 实现自适应预算选择；该职责属于后续预算规划器任务。
