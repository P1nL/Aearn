# Tutor 上下文预算评估与可观测性实施计划

## 开始前置条件

- 前四个 child 已完成并归档或通过完整验收。
- 读取最终 current-input、usage、budget、summary contract，而不是按早期规划假设编写 eval。
- 默认保持 fake/offline；真实 provider 只在显式开关下运行。

## 有序实施清单

### 1. 扩展 Eval Schema

- 为 source-controlled Tutor eval fixture 增加 capability/budget/conversation/summary/usage 期望。
- 增加安全结果 schema 和版本化验证。
- 旧 fixture 保持兼容或显式迁移。

### 2. 增加 Current-Input/History Cases

- current pinned；
- newest history；
- no duplication；
- equal timestamp；
- provider-not-called failure；
- proactive compatibility。

### 3. 增加 Usage Cases

- cached token 非重复计算；
- no-cache/missing usage；
- repair attempt 分开；
- invalid decision receipt；
- reported/calculated total。

### 4. 增加 Budget Cases

- compact/normal/complex/extended；
- warning/critical eviction；
- hard-limit fail；
- bounded upgrade；
- deterministic replay。

### 5. 增加 Summary Cases

- incremental retirement；
- coverage cursor；
- correction override；
- stale/cross-scope exclusion；
- curator unavailable；
- no raw evidence persistence。

### 6. 实现 Calibration 报告

- 汇总 estimate vs actual error；
- 按 provider/protocol/mode 分组；
- 输出安全数字/boolean/enum；
- 添加测试阈值和版本，不自动改生产设置。

### 7. 实现 Optional Real Smoke

- 增加显式环境开关/pytest marker/命令。
- 运行报告中的五轮对话。
- 保存 learner-safe 回复、usage、mode、latency 和 rubric。
- credential、prompt、provider body、reasoning 永不输出。

### 8. 文档和 Release Ledger

- 更新 runtime、acceptance matrix、release-readiness 和 backend spec。
- 明确 fake contract、real behavior evidence 和 release approval 三者的区别。

## 预期实施范围

- `aearn/services/api/app/services/tutor/evals.py`
- `aearn/services/api/tests/test_tutor_evals.py`
- `aearn/services/api/tests/fixtures/tutor_evals/`
- 新增或扩展 context/usage/budget/summary 专项 tests
- 可选 `aearn/services/api/tests/test_tutor_real_provider_smoke.py`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/qa/acceptance-test-plan.md`
- `docs/qa/tutor-harness-release-readiness.md`
- `.trellis/spec/backend/quality-guidelines.md`

## 必需验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_evals.py tests/test_tutor_context_builder.py tests/test_tutor_provider_gateway.py tests/test_tutor_run_loop.py -q
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\api lock --check
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-tutor-context-budget-evals-observability
git diff --check
```

可选真实 smoke 仅在单独批准并完成配置后执行。

## 风险与回滚

- 不要用 fake response 宣称真实教学质量。
- 不要把 token 使用率当质量指标。
- 不要让 eval fixture 含真实 credential 或 provider body。
- 不要在 eval task 中绕过 owning child 的 contract bug。
- 可关闭真实 smoke 和 calibration aggregate，不影响离线 suite。

## `task.py start` 前审查门

- 前四个 child 已完成。
- 安全指标、真实 smoke 输出边界和 calibration 阈值已最终审查。
- 展示最终计划并等待单独实施批准。