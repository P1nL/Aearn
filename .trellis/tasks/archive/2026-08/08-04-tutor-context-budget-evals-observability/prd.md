# Tutor 上下文预算评估与可观测性

## 目标

为完整 Tutor 上下文治理链路建立确定性回归、数值可观测性和受控真实 provider smoke，证明当前输入、历史选择、自适应预算、缓存计量、增量摘要和教学相关性在不同对话长度与 provider 能力下保持正确，并用真实 usage/延迟证据校准档位，而不是用“上下文使用率越高越好”作为质量目标。

## 依赖

- 父任务：`08-04-tutor-context-governance-adaptive-budget`。
- 依赖以下子任务完成并提供稳定 contract：
  - `08-04-tutor-latest-input-teaching-relevance`
  - `08-04-tutor-provider-usage-cache-accounting`
  - `08-04-tutor-adaptive-context-budget-planner`
  - `08-04-tutor-context-summary-retrieval-compaction`
- 本任务是任务树的集成验收子任务，不替代各 child 自身的聚焦测试。

## 需求

### E1 — 确定性 Context Fixtures

至少增加以下离线场景：

- `current_input_pinned`
- `newest_history_selected`
- `current_input_not_duplicated`
- `optional_context_evicted_first`
- `required_input_unrepresentable_provider_not_called`
- `usage_cached_tokens_not_double_counted`
- `repair_attempts_accounted_separately`
- `compact_turn_uses_small_budget`
- `complex_turn_expands_budget`
- `physical_hard_limit_never_exceeded`
- `summary_covers_retired_messages_once`
- `summary_does_not_override_correction`
- `stale_summary_excluded`

所有普通 CI 场景使用 fake provider、固定时钟、固定 token estimator 和本地 PostgreSQL fixture，不访问网络。

### E2 — 安全数值指标

每个 run/attempt 允许记录以下安全 metadata：

- `budget_mode`
- `estimated_total_input_tokens`
- `estimated_dynamic_context_tokens`
- `actual_input_tokens`
- `cached_input_tokens`
- `uncached_input_tokens`
- `output_tokens`
- `total_tokens`
- `selected_count` / `skipped_count` / `truncated_count`
- `budget_expansion_count`
- `compaction_trigger`
- `summary_coverage_count`
- `first_token_latency_ms` 或 provider 可得的等价安全延迟
- estimator/config/schema version

不得记录正文、prompt、history、provider body、reasoning、路径、命令或 credential。

### E3 — 质量 Rubric

评估不能只看 token 使用率，至少包含：

- 最新输入存在且被直接回答；
- 用户纠正得到简短确认；
- 已完成/已拒绝步骤不被重复；
- 建议类问题先回答；
- 不强制继续陈旧教学路径；
- 选入上下文与当前问题相关；
- 必需上下文密度和 optional context 利用率；
- 平均/P95 输入 token、输出 token、缓存比例和首字延迟；
- provider-not-called 安全失败是否正确。

### E4 — Budget Calibration

- 对 compact/normal/complex/extended 档位使用同一 fixture 集比较相关性、token、延迟和失败率。
- actual usage 与请求前估算的误差需要分 provider/protocol 汇总；超出容许误差时调整 estimator 或 safety margin，而不是隐藏差异。
- 最终推荐默认档位和 warning/critical ratio 必须来自版本化 eval 证据，并保持可配置。
- 不以“使用了 1M 窗口的百分比”作为单独成功标准。

### E5 — 可选真实 Provider Smoke

- 基于报告中的真实五轮对话运行受控 smoke：
  1. `我想做个网站`
  2. `绘画作品，迪士尼风格，零基础`
  3. `我已经有了`
  4. `你不是应该教我编程语言吗`
  5. `我应该学哪些语言`
- 只在显式启用且 provider 已配置时运行；默认 CI 跳过。
- 输出只包含 learner-safe Tutor 回复、token 数、缓存比例、档位、延迟和 rubric boolean。
- 不打印或持久化 API key、raw prompt、provider request/response、reasoning 或 transport body。
- smoke 是模型行为证据，不是确定性 contract 测试或发布批准的替代品。

### E6 — 文档与 Release Evidence

- 更新 `docs/qa/acceptance-test-plan.md` 和 `docs/architecture/tutor-harness-runtime.md`。
- 如果真实 smoke 被执行，将命令、环境边界、数值结果、非声明和剩余风险记录到 release-readiness ledger；不得把单次成功描述为普遍质量保证。

## 验收标准

- [ ] 所有列出的确定性 fixture 离线通过，并能精确断言 provider 调用次数和上下文 metadata。
- [ ] usage fixture 正确区分 input/cached/uncached/output/total，repair attempt 不被合并丢失。
- [ ] compact 问题不会无意义使用 extended 档位；复杂长文档/早期历史引用场景能够有界扩容。
- [ ] 任意档位的估算总输入都不超过 provider physical capacity；必要输入无法容纳时 provider 未调用。
- [ ] 摘要只覆盖退休消息一次，最新纠正始终覆盖旧 summary/memory 假设。
- [ ] trace、receipt、日志和测试快照均不包含 raw prompt、history、provider body、reasoning 或 credential。
- [ ] actual-vs-estimated 误差报告可用于调整 estimator/safety margin，并按 provider/protocol 区分。
- [ ] 可选真实 smoke 有明确启用方式和 bounded rubric；未配置时稳定 skip。
- [ ] 完整相关 API 测试、Ruff、Mypy、锁文件检查、Desktop check、任务验证和 `git diff --check` 通过，或阻塞被精确记录。

## 范围外

- 将真实 provider smoke 加入默认 CI。
- 构建面向用户的费用账单、token dashboard 或管理员分析产品。
- 自动修改生产配置、发布阈值或 provider/model routing。
- 将单次 smoke 结果声明为发布批准或模型质量保证。
