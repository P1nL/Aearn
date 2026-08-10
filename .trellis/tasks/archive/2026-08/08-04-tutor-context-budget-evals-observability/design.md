# Tutor 上下文预算评估与可观测性设计

## 设计目标

本任务不再定义新的上下文选择语义，而是把前四个子任务形成的 contract 组合成可重复、可校准、可审计的质量证据。评估体系必须同时回答三类问题：

1. **正确性**：当前输入、近期历史、摘要、缓存计量和物理上限是否符合 contract；
2. **效率**：不同预算档位的估算、实际 token、缓存比例和延迟是否合理；
3. **教学质量**：Tutor 是否直接回应最新意图、尊重纠正并避免重复陈旧路径。

不得用单一“上下文窗口使用率”代替上述三类证据。

## 分层架构

### 第一层：确定性 Contract Fixtures

默认 CI 运行，不访问网络。使用 fake provider、固定时钟、固定 token estimator、本地 PostgreSQL fixture 和确定性的 provider capability registry，精确断言：

- 输入排序、去重和不可驱逐规则；
- provider 是否被调用以及调用次数；
- budget mode、选择/跳过/截断数量；
- usage receipt 的 attempt 粒度和缓存非重复计数；
- 摘要 coverage、冲突优先级和过期排除；
- 安全失败时不存在副作用或 raw evidence 泄漏。

这一层是发布回归 contract 的主要来源。

### 第二层：离线 Calibration

对同一组 fixtures 运行 compact、normal、complex、extended 档位，比较：

- 请求前估算与 provider 返回实际输入 token 的差异；
- optional context 的选入密度；
- 缓存命中比例；
- 输出 token 和首字延迟；
- 失败、扩容和压缩触发情况；
- 教学相关性 rubric。

Calibration 只生成版本化报告和调整建议，不自动修改生产配置。

### 第三层：可选真实 Provider Smoke

仅在显式设置 `TUTOR_REAL_PROVIDER_SMOKE=1` 且 provider 配置完整时执行。它使用固定五轮对话验证真实模型行为，但不进入默认 CI，也不替代确定性测试或发布审批。

### 第四层：Release Evidence

将测试命令、fixture/schema 版本、数值结果、未运行项、限制和剩余风险写入 QA 文档与 release-readiness ledger。证据必须区分：

- fake contract 已验证；
- real provider behavior 已抽样；
- release approval 尚需人工决策。

## Fixture Contract

建议在现有 Tutor eval fixture schema 上增量增加以下字段：

```json
{
  "schema_version": 2,
  "case_id": "current_input_pinned",
  "provider_capability": {
    "provider": "fake-openai-compatible",
    "protocol": "responses",
    "model": "fixture-model",
    "physical_context_window": 65536,
    "max_output_tokens": 4096
  },
  "budget_policy": {
    "requested_mode": "normal",
    "allow_bounded_expansion": false
  },
  "conversation": {
    "current_input": {},
    "recent_messages": [],
    "working_summary": null,
    "learner_memory": [],
    "activity": []
  },
  "provider_attempts": [],
  "expected": {
    "provider_call_count": 1,
    "selected_source_ids": [],
    "excluded_source_ids": [],
    "budget_mode": "normal",
    "rubric": {}
  }
}
```

约束：

- fixture 中只能使用合成 learner-safe 内容；
- source IDs 固定且可复现；
- equal timestamp 场景必须以 `(created_at, message_id)` 断言稳定顺序；
- usage 缺失使用显式 `null/unknown`，不能伪造为零；
- 旧 fixture 可通过兼容 loader 读取，迁移后必须固定 schema version。

## 执行数据流

```text
fixture
  -> 固定 capability + estimator + clock
  -> Tutor 输入装配
  -> budget planner
  -> fake/real provider attempt
  -> usage attempt receipt
  -> summary/compaction side effect
  -> 安全 eval receipt
  -> aggregate calibration / rubric report
```

每一层只消费上一层公开 contract。Eval 不得直接修改生产 planner、summary 或 provider 逻辑来“让测试通过”。

## 安全 Eval Receipt

每个 case 生成结构化 receipt，字段限定为数字、布尔值、枚举、版本和不透明 ID：

```json
{
  "case_id": "complex_turn_expands_budget",
  "fixture_schema_version": 2,
  "estimator_version": "v1",
  "budget_config_version": "v1",
  "provider": "fake-openai-compatible",
  "protocol": "responses",
  "budget_mode": "complex",
  "estimated_total_input_tokens": 120000,
  "actual_input_tokens": 118500,
  "cached_input_tokens": 80000,
  "uncached_input_tokens": 38500,
  "output_tokens": 1200,
  "total_tokens": 119700,
  "selected_count": 9,
  "skipped_count": 3,
  "truncated_count": 0,
  "budget_expansion_count": 1,
  "summary_coverage_count": 42,
  "provider_called": true,
  "rubric": {}
}
```

禁止字段包括 prompt、message content、history、provider request/response body、reasoning、credential、命令、路径和任意可还原 learner 文本的摘要。

## 数值定义

- `cached_input_tokens` 是 `actual_input_tokens` 的子集；
- `uncached_input_tokens = actual_input_tokens - cached_input_tokens`，仅在两者均已知且数值合法时计算；
- `cache_ratio = cached_input_tokens / actual_input_tokens`，输入为零或 usage 缺失时记为 unknown；
- `estimation_delta = actual_input_tokens - estimated_total_input_tokens`；
- `estimation_error_ratio = estimation_delta / max(actual_input_tokens, 1)`；
- reported total 与 calculated total 分开保留，不能静默覆盖 provider 原值；
- repair、retry 和 bounded expansion 的每个 HTTP attempt 单独计量，run aggregate 由 receipt 汇总产生。

报告至少按 provider、protocol、model capability、budget mode、estimator version 和 config version 分组。P50/P95 只在样本量满足报告门槛时展示，否则标记样本不足。

## 教学相关性 Rubric

每个适用 case 输出固定 boolean，不保存自由文本推理：

- `answers_current_input`
- `acknowledges_user_correction`
- `avoids_repeating_completed_steps`
- `avoids_rejected_path`
- `answers_advice_before_procedure`
- `does_not_force_stale_teaching_path`
- `selected_context_is_relevant`
- `provider_safely_not_called_when_required`

离线 fake cases 主要验证结构和决策 contract；真实 smoke 才能提供模型行为样本。两者不得混写成同一种质量结论。

## 场景矩阵

### Current Input 与 History

- 权威 current input 永远存在且只出现一次；
- 最新历史优先，时间戳相同时按 message ID 稳定排序；
- optional context 先于 current input 被驱逐；
- 必需输入无法容纳时 provider 未调用。

### Usage 与 Cache

- cached token 不与 input token 相加造成双重计数；
- repair attempts 分开保存；
- usage 缺失保持 unknown；
- provider reported total 与 calculated total 差异可见。

### Budget

- compact 请求不无意义进入 extended；
- complex/extended 只在复杂度和证据需求满足条件时使用；
- warning/critical 水位按固定顺序驱逐 optional context；
- hard limit 前安全失败；
- `insufficient_context` 最多按配置进行有界扩容。

### Summary

- 只压缩退休消息；
- coverage cursor 不重复覆盖；
- 最新纠正覆盖旧 summary/memory；
- stale、cross-user、cross-conversation 摘要不注入；
- curator 不可用时回退 current + recent，原始消息仍保留。

## 真实 Provider Smoke

真实 smoke 使用 PRD 中固定五轮对话，执行边界如下：

- 默认 skip；
- 显式开关和 provider 配置缺一不可；
- 使用隔离的测试 user/conversation/run 标识；
- 限制最大轮数、最大输出、超时和总 attempt 数；
- 只输出 learner-safe 回复、数字、枚举和 rubric boolean；
- 失败时清理测试作用域数据，不打印 transport body；
- 结果必须注明 provider、model、protocol、执行日期和配置版本，但不得包含 credential。

建议命令形式：

```text
TUTOR_REAL_PROVIDER_SMOKE=1 uv --directory ./aearn/services/api run python -m pytest tests/test_tutor_real_provider_smoke.py -q -m real_provider
```

## 兼容、迁移与回滚

- Eval schema 采用 additive/versioned 迁移；旧 fixtures 在迁移窗口内由兼容 loader 读取；
- 新 receipt 字段缺失时按 unknown 处理，不把旧数据回填为零；
- calibration 报告不参与在线请求路径，关闭后不影响 Tutor 运行；
- real smoke marker 可独立关闭；
- 若新指标可能暴露文本，立即停止持久化该字段并保留数值最小集；
- 若前置 child contract 发生变化，先更新 owning child 测试，再更新集成 fixture，禁止在本任务建立第二套语义。

## 文档边界

实施完成后同步：

- `docs/architecture/tutor-harness-runtime.md`：运行时预算、usage、summary 和 eval 边界；
- `docs/qa/acceptance-test-plan.md`：确定性场景矩阵和执行命令；
- `docs/qa/tutor-harness-release-readiness.md`：实际执行证据、非声明和剩余风险；
- `.trellis/spec/backend/quality-guidelines.md`：可执行的长期回归 contract。