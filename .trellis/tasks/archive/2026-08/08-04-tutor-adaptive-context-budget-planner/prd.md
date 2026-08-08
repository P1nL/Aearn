# Tutor 自适应上下文预算规划器

## 目标

在 provider 物理上下文边界内，为每个 Tutor TurnRun 计算完整请求预算，并根据当前问题的复杂度和证据需求选择紧凑、普通、复杂或扩展档位。普通请求不无意义填满大窗口，复杂请求又能可靠扩展到数十万 token；任何档位都必须先保留权威当前输入，并按确定性优先级驱逐可选上下文。

## 依赖

- 父任务：`08-04-tutor-context-governance-adaptive-budget`。
- 依赖 `08-04-tutor-latest-input-teaching-relevance` 提供 required `current_input` 和可选上下文分离 contract。
- 依赖 `08-04-tutor-provider-usage-cache-accounting` 提供实际 provider usage，用于估算误差和档位校准；planner 在请求前不得依赖缓存一定命中。
- 完成后为 `08-04-tutor-context-summary-retrieval-compaction` 提供近期窗口和 compaction 高水位决策。

## 已确认事实

1. 当前精确 `deepseek-v4-flash` 的物理输入容量是 `616_000` token，但 `TutorContextBuilder` 只估算选中 context item，没有完整覆盖 system prompt、教学策略、JSON 外壳、metadata 和安全余量。
2. 非精确 DeepSeek/OpenAI-compatible 模型当前没有统一可靠的 model context catalog；未知能力必须保守配置，不得从模型名猜测。
3. 缓存读取 token 仍占用模型物理上下文；请求前缓存命中未知，因此硬边界必须按完整序列化输入估算。
4. 当前 item limits 与固定优先级提供了确定性基础，但没有任务复杂度档位、完整请求 reserve、自动扩容或真实 usage 校准。

## 需求

### B1 — Provider Capability Contract

- 为 Tutor provider 配置显式的 context window、最大输出 reserve、protocol reserve、安全余量和动态上下文最大值。
- 精确 `deepseek-v4-flash` 继续使用已验证的 1M/384K 物理配置。
- 未知 provider/model 保持现有保守预算，除非显式配置或受测试的 model capability registry 提供证据；不得猜测上下文窗口。
- 配置验证必须保证输出 reserve、protocol reserve 和 safety margin 后仍有正的必需输入空间。

### B2 — 完整请求预算

- 请求前估算：system/protocol instruction、严格 JSON contract、current input、选中上下文、context metadata、capability schema、JSON 序列化开销和 safety margin。
- `TutorContextBuilder` 不再独占整个 provider input capacity；planner 向 builder 传递剩余动态预算。
- 估算必须保守、provider-neutral 且可替换；actual usage 用于离线校准，不用于为已发出的同一请求追溯修改预算。

### B3 — 自适应档位

- 至少支持 `compact`、`normal`、`complex`、`extended` 四个确定性档位。
- 初始代表性目标可在测试/配置中使用 16K、64K、192K、384K，但必须被 provider capacity 裁剪，且不得成为跨模型不可变常量。
- 档位选择信号只能来自安全、可测试的请求事实，例如：
  - 当前输入长度与结构；
  - 是否明确引用早期对话；
  - 是否要求比较多个既往方案；
  - 是否包含长代码/错误日志/文档引用；
  - 相关检索候选数量与高分证据；
  - working summary 是否缺失或覆盖不足。
- 不使用模型自由文本自报复杂度作为唯一预算升级依据。

### B4 — 扩容与收缩

- 简单、直接问题默认选择紧凑档位；仅当证据需求存在时升级。
- 同一 TurnRun 可在 `insufficient_context` 等受控内部结果后最多进行有界升级，并受现有 `max_iterations`/`max_model_calls` 限制。
- 接近 warning/critical ratio 时，按治理优先级压缩或驱逐 optional context，不删除 current input。
- 不以“模型支持 1M”或“缓存便宜”为填满上下文的理由。

### B5 — 选择和驱逐优先级

- 必需层：system/protocol + current input。
- 高优先级可选层：最新既往消息、与当前问题直接相关的 active plan/review。
- 中优先级层：working summary、相关 learner memory。
- 低优先级层：activity 和非必要 capability schema。
- 实际 schema 可按已授权 capability 需要提前预留，但不得让无关 schema 挤掉当前输入或最新历史。

### B6 — Metadata 与安全

- checkpoint/trace 只记录 budget mode、估算总量、动态预算、selected/skipped/truncated count、source IDs/hashes、warning/critical 状态和估算版本。
- 不记录 raw prompt、历史正文、provider payload、reasoning 或 credential。
- estimator/version/config 必须进入 policy fingerprint，保证重放和回归可解释。

## 验收标准

- [ ] planner 计算的完整估算包含 system、current input、context、metadata、schema、JSON overhead 和 safety margin。
- [ ] 缓存 token 计入 actual physical total；请求前不因预期 cache hit 放宽硬边界。
- [ ] 简单问题选择紧凑/普通档位，复杂长文档问题能升级到更大档位，且两者均不突破 provider capacity。
- [ ] 代表性 16K/64K/192K/384K 目标只作为可配置、可校准档位，并按不同 provider 能力裁剪。
- [ ] budget 紧张时先驱逐低优先级 optional context；current input 与必要 protocol 始终保留。
- [ ] 必需内容无法容纳时，provider 调用次数为零，并返回类型化安全失败。
- [ ] 同一输入和同一配置得到确定相同的档位、预算和选择 metadata。
- [ ] actual usage 与估算误差可被 eval 记录，但公开 API/SSE 不暴露内部 token 细节。
- [ ] 聚焦单元测试、run-loop/context/provider 测试、Ruff、Mypy、任务验证和 `git diff --check` 通过。

## 范围外

- 自动切换 provider/model/protocol。
- 预测或保证 provider cache hit。
- 通过实时定价选择预算档位。
- 把 1M 窗口设为每次请求必须达到的使用率目标。
- 实现长期结构化摘要的生成与检索；该职责属于后续摘要任务。
