# Tutor 自适应上下文预算规划器实施计划

## 开始前置条件

- Child 1 的 required current-input contract 已完成。
- Child 2 的 usage contract/receipt 已完成并可用于测试校准。
- 重新读取当前 Settings、context builder、provider message serializer、run policy persistence 和所有重叠 diff。

## 有序实施清单

### 1. 建立 Provider Capability Registry

- 定义显式 `TutorProviderContextCapability`。
- 为精确 `deepseek-v4-flash` 注册已验证 1M/384K contract。
- 为其他 provider/model 使用显式配置或现有保守默认。
- 增加配置交叉验证和 capability version。

### 2. 拆分完整请求 Serializer

- 将 provider system/payload 构造提取为 deterministic serializer。
- 支持 dry-build 供 planner 估算和正式 build 供 gateway 调用。
- 保证 initial 与 repair 共享 teaching/protocol contract。

### 3. 实现 Budget Planner

- 增加 mode enum、plan contract 和 estimator version。
- 计算 required estimate、physical optional capacity、mode target 和最终 optional budget。
- 必需内容超 hard limit 时抛出类型化 context budget error。

### 4. 实现确定性 Mode Classifier

- 定义 compact/normal/complex/extended 的安全结构化 signal。
- 不使用 keyword-specific 中文答案或模型自由文本决定预算。
- 测试相同输入/配置得到相同 mode。

### 5. 重构 ContextBuilder

- 接收 `TutorContextBudgetPlan` 或明确 optional budget。
- 按新的 required/optional priority 选择来源。
- 记录 selected/skipped/truncated 与 budget mode。
- 修正 high-water 依据，避免仍用物理总容量的固定 80% 造成永不触发。

### 6. 接入 Run Policy 与有界升级

- 在新 run policy 中冻结 capability/budget/estimator version。
- run loop 支持最多一个档位一级升级或配置的有界次数。
- 每次升级前重检 supersede、cancellation 和 input revision。
- 旧 run 保持 legacy budget 兼容。

### 7. Actual Usage 校准

- 测试中比较 estimate 与 actual usage receipt。
- 定义按 provider/protocol 的允许误差和安全 margin 测试，不在运行时自动修改配置。
- 记录安全 calibration metadata。

### 8. 文档与规格

- 更新环境配置示例、runtime architecture、QA matrix 和 backend quality contract。
- 明确 1M 是能力，不是每轮填满目标；缓存计入 physical total。

## 预期实施范围

- `aearn/services/api/app/core/config.py`
- `aearn/services/api/app/agents/harness/contracts.py`
- `aearn/services/api/app/agents/harness/context_builder.py`
- 新的 context budget/planner 模块（放在 `app/agents/harness/` 或相邻 Tutor runtime 层）
- `aearn/services/api/app/services/tutor/provider_gateway.py`
- `aearn/services/api/app/services/tutor/public_api.py`
- `aearn/services/api/app/services/tutor/run_loop.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/tests/test_tutor_context_builder.py`
- `aearn/services/api/tests/test_tutor_provider_gateway.py`
- `aearn/services/api/tests/test_tutor_run_loop.py`
- `aearn/services/api/tests/test_tutor_input_merge.py`
- `aearn/.env.example`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/setup/development-environment.md`
- `docs/qa/acceptance-test-plan.md`
- `.trellis/spec/backend/quality-guidelines.md`

## 必需验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_context_builder.py tests/test_tutor_provider_gateway.py tests/test_tutor_run_loop.py tests/test_tutor_input_merge.py -q
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\api lock --check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-tutor-adaptive-context-budget-planner
git diff --check
```

## 风险与回滚

- 不要用模糊模型名推断超大窗口。
- 不要只估算 context items 而遗漏 protocol/JSON/schema。
- 不要根据预期缓存命中扣减 physical estimate。
- 不要允许无限 `insufficient_context` 升级。
- 如自适应 classifier 不稳定，可回滚为保守固定 `normal` mode，但保留完整请求硬边界和 current input invariant。

## `task.py start` 前审查门

- Child 1、Child 2 均已完成。
- capability registry、代表性档位和升级上限已通过最终规划审查。
- 展示最终计划并等待单独实施批准。