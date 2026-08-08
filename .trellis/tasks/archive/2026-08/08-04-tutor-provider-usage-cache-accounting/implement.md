# Tutor Provider Usage 与缓存计量实施计划

## 开始前置条件

- `08-04-tutor-latest-input-teaching-relevance` 已完成并冻结 provider payload/current-input contract。
- 重新读取 `llm_client.py`、`provider_gateway.py`、`run_loop.py`、`persistence.py`、`safe_projection.py`、schema 和重叠工作树 diff。
- 保留现有 primary-only、repair、DeepSeek exact-model routing 和用户修改。

## 有序实施清单

### 1. 固化 Usage 类型

- 在共享 LLM client 边界增加 `LLMUsage`。
- 为 `LLMJsonResponse` 增加可选 usage。
- 实现 token 非负、cached <= input 和 uncached 派生验证。
- 保持旧 fake/client 构造兼容。

### 2. 解析 Responses Usage

- 扩展最终 Responses envelope 提取 helper。
- 从 nested `usage` 解析 input/cached/output/total/reasoning 数值。
- 覆盖 streaming `response.completed`。
- 添加 malformed/partial/missing usage 测试。

### 3. 解析 Chat Completions Usage

- 解析 prompt/completion/total 及 cached prompt details。
- 归一化为相同 `LLMUsage`。
- 不假设所有 compatible provider 都返回 OpenAI 完整字段。

### 4. 记录 Gateway Attempt

- 为每个首次/repair 调用创建 `TutorProviderAttemptReceipt`。
- 在 accepted、repairable rejected、terminal rejected 和 transport failed 路径中返回安全 attempt tuple。
- 保证 rejected response body 或 validation detail不进入 receipt。

### 5. 增加数据库 Contract

- 更新 `app/db/schema.sql`，增加 scoped append-only receipt 表、约束和索引。
- 更新 `docs/architecture/database-schema.md`。
- 添加 repository/lifecycle 写入与幂等读取 helper。
- 根据需要扩展 safe projection allowlist。

### 6. 接入 Run Loop 与 Persistence

- 为每次 provider decision 提供稳定 `decision_iteration`。
- 在 provider 返回后保存 attempt receipts，同时保持 supersede/cancel 防线。
- 不改变 `model_call_count`、public API/SSE 和 terminal outcome。
- receipt persistence 冲突采用类型化内部失败，不泄露 token/provider 细节。

### 7. 测试与审计

重点测试：

- `175420 input / 170368 cached / 2223 output`；
- 无缓存；
- usage 缺失；
- cached > input 拒绝；
- Responses streaming；
- Chat Completions；
- invalid JSON 后 repair；
- 两个 attempt 分别持久化；
- superseded run 只留 usage，不写业务结果；
- 跨用户/重复 identity 拒绝；
- trace/export/log 不泄露正文。

## 预期实施范围

- `aearn/services/api/app/services/llm/llm_client.py`
- `aearn/services/api/app/services/tutor/provider_gateway.py`
- `aearn/services/api/app/services/tutor/run_loop.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/services/tutor/safe_projection.py`
- `aearn/services/api/app/agents/harness/contracts.py`（仅在 receipt 需要跨层 contract 时）
- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/tests/test_tutor_provider_gateway.py`
- `aearn/services/api/tests/test_tutor_run_loop.py`
- `aearn/services/api/tests/test_tutor_run_repository.py`
- `aearn/services/api/tests/test_db_bootstrap.py`
- `docs/architecture/database-schema.md`
- `docs/architecture/tutor-harness-runtime.md`
- `.trellis/spec/backend/quality-guidelines.md`

## 必需验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_provider_gateway.py tests/test_tutor_run_loop.py tests/test_tutor_run_repository.py tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\api lock --check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-tutor-provider-usage-cache-accounting
git diff --check
```

## 风险与回滚

- 不要把 `input_tokens + cached_tokens` 当作总输入。
- 不要让 usage 缺失变成 Tutor failure。
- 不要因为 receipt 是内部数据就保存 provider body。
- 如持久化 contract 风险过大，可先回滚数据库写入并保留内存 usage contract/tests；不得改变模型路由或删除数据。

## `task.py start` 前审查门

- 确认 Child 1 已完成。
- 确认 attempt identity、usage 缺失语义和 receipt 持久化位置已在最终设计中固定。
- 展示最终计划并等待单独实施批准。