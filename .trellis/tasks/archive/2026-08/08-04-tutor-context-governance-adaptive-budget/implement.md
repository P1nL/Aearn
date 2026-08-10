# Tutor 上下文治理与自适应预算总体实施计划

## 开始前置条件

- 父任务保持 `planning`，通常不执行 `task.py start`；实际实现从依赖满足的 child 开始。
- 当前首个可实施 child 是 `08-04-tutor-latest-input-teaching-relevance`。
- 每个 child 在实施前单独完成 planning review、真实 context manifests 和 `task.py start`。
- 不提交、推送、部署或修改生产数据，除非用户另行明确批准。

## 有序任务清单

### 1. Child 1 — 最新输入与教学相关性

- 精确解析 current input。
- 修正最新历史选择。
- current input 独立进入 provider payload。
- 加入 latest-intent/correction teaching policy。
- 完成确定性回归。

**Gate：** current input contract、loader/query、builder required source 和 provider payload 稳定后，才进入 Child 2。

### 2. Child 2 — Provider Usage 与缓存计量

- 扩展统一 LLM response/usage contract。
- 保留 Responses stream/Chat Completions usage。
- 为每个实际 attempt 写安全 receipt。
- 明确 input/cached/uncached 的非重复计算。

**Gate：** usage fixture 与持久化幂等通过后，才用于预算校准。

### 3. Child 3 — 自适应预算 Planner

- 建立 provider capability/reserve contract。
- 估算完整序列化请求。
- 实现 compact/normal/complex/extended 档位。
- 实现 warning/critical 驱逐与有界升级。

**Gate：** 所有档位均证明不突破物理硬上限，current input 永不被驱逐。

### 4. Child 4 — 长对话摘要闭环

- 扩展 summary schema 与 conversation coverage。
- worker 按 source ID/hash 临时加载退休消息。
- 增量生成结构化摘要。
- loader 接入 valid summary，固定冲突优先级。

**Gate：** 摘要失败不删消息、不泄露、不覆盖当前纠正。

### 5. Child 5 — 综合 Eval 与可观测性

- 汇总跨层 fixtures。
- 建立 actual-vs-estimated calibration。
- 增加安全数值指标。
- 提供显式可选真实 provider smoke。
- 更新 QA 和 release evidence。

### 6. 父任务集成验收

- 检查所有 child 已完成/归档并满足依赖。
- 对照父 PRD 运行完整相关 API、lint、type、lock、Desktop 与 diff hygiene。
- 更新 source-of-truth 和 backend reusable contract。
- 父任务仅在完整集成验收后归档。

## 跨任务验证

```powershell
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\api lock --check
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-tutor-context-governance-adaptive-budget
git diff --check
```

数据库支持的测试必须串行。真实 provider smoke 不属于默认验证，只在明确批准和配置后执行。

## 审查门

- 本任务树的规划完成不等于任何 child 的实施批准。
- 下一步应先审阅并批准 Child 1，然后只启动 Child 1。
- 后续 child 必须在前置 child 验证通过后分别审批启动。