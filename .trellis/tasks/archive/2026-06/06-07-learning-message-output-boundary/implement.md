# Implementation Plan: Learning Message Public Output Boundary

## Preconditions

- 本任务保持 `planning`，直到用户审核 `prd.md`、`design.md`、`implement.md` 和 `review.zh.md`。
- 实施前运行 `trellis-before-dev`，读取 backend/frontend index、quality、error handling、type safety 和 cross-layer guides。
- 当前工作树已有 `06-06-learning-flow-concept-docs-refinement` 未提交改动；不得覆盖或回退。
- 不在本任务中实现句子/段落 SSE 缓冲。

## Phase 1: Contract and tests first

1. 更新 `docs/architecture/api-contract.md`：
   - 定义结构化模型 envelope 与 internal-review 非公开边界。
   - 保留 `agent_message.content` 和 SSE 事件兼容。
2. 更新 `docs/product/frontend-interaction-spec.md`：
   - 明确不展示“导师判断”或思考过程。
   - 禁止前端从正文猜测内部内容。
3. 更新 `docs/qa/acceptance-test-plan.md`：
   - 增加 envelope 隔离、SSE 解包、回放和 provider 兼容验收。
4. 先添加失败测试，锁定：
   - prompt payload 不含内部 policy 对象。
   - SSE 不发 envelope key/internal review。
   - internal review 不持久化或返回。

## Phase 2: Typed directive and prompt cleanup

1. 在学习 conversation service 中定义 `LearningReplyDirective`。
2. 把 `_response_policy()` 的分支迁移为 typed directive builder。
3. 新增 directive-to-instructions compiler。
4. 从模型 user JSON 删除：
   - `response_policy`
   - `stage_strategy`
   - `forbidden_outputs`
   - `allowed_outputs`
   - 其他仅用于后端控制的 policy 字段。
5. 保持 system prompt 通用；删除“针对某个泄漏词”的流程性特化。
6. 更新 prompt snapshot/contract tests。

## Phase 3: Structured output schema and provider adapters

1. 新增 `LearningPublicOutput` 和 `LearningOutputReview` schema。
2. 增加统一的 structured stream client protocol。
3. OpenAI Agents SDK：
   - 为主 Agent 和 handoff Agent 配置 `output_type`。
   - 保留 tools、guardrails、routing 和 tracing 边界。
   - 验证 final output 类型。
4. DeepSeek：
   - 增加 `response_format=json_object` 的 streaming transport。
   - 保持 `reasoning_content` 忽略行为。
5. 非法/空 structured output 映射为现有 `LLMInvalidResponseError`。

## Phase 4: Incremental decoder and shared generation flow

1. 实现 bounded `LearningOutputStreamDecoder`。
2. 覆盖任意 chunk、escape、Unicode、字段乱序和不完整 JSON。
3. service 产生 typed public delta/completed events。
4. JSON collector 和 SSE route 使用同一 parser/validator。
5. 每个公开 delta 继续经过增量 guardrail。
6. 完成时：
   - 完整 parse + Pydantic 校验。
   - 校验 internal review flags。
   - 校验最终正文。
   - 确认 streamed public text 等于最终 `public_message`。

## Phase 5: API persistence and replay

1. `agent_message.content` 写入 `public_message`。
2. 丢弃 `internal_review`。
3. JSON response 只返回正式正文。
4. SSE 不发送 envelope/internal fields 或额外诊断摘要。
5. 幂等回放和学习历史只恢复正式正文与工具调用。
6. 保持 tool calls、stage writes 和 idempotency success timing 不变。

## Phase 6: Frontend public-message-only rendering

1. 保持 frontend types 和 API guards 只接收正式消息正文。
2. 不渲染“导师判断”或 raw thinking，不从正文做正则提取。
3. 保持现有 Agent 消息 UI。

## Tests

### Backend unit tests

- structured schema valid/invalid cases。
- internal review false -> invalid。
- incremental decoder：
  - 每个字符一个 chunk。
  - escaped quote/backslash/newline。
  - `\uXXXX` 跨 chunk。
  - `public_message` 字段顺序变化。
  - truncated/oversized/duplicate field。
- DeepSeek reasoning content ignored。
- DeepSeek streaming payload includes JSON response format。
- Agents SDK receives structured `output_type`。
- prompt payload contains learning facts but no internal policy object。

### Backend API tests

- JSON success exposes only public message。
- SSE emits only decoded public deltas, tool calls, done。
- screenshot-like `_policy...符合policy要求` candidate -> `MODEL_UNAVAILABLE`, no persistence。
- invalid envelope/internal review failure -> `MODEL_UNAVAILABLE`。
- partial SSE failure -> error, no assistant row/idempotency success。
- idempotent replay and history restore public message。
- practice unlock and concept feedback tools remain ordered and non-duplicative。

### Frontend tests/checks

- no diagnostic summary in public types。
- message/SSE merge behavior。
- no mentor-judgement or thinking rendering。
- no diagnostic/internal-review field accepted by public API types。

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-07-learning-message-output-boundary
git diff --check
```

如果新增独立 decoder test 文件，将其加入 focused pytest 命令。

## Manual Verification

1. OpenAI/compatible provider：普通学习回复持续流式显示，页面不出现 JSON key。
2. DeepSeek：reasoning 字段不显示，正文正常流式显示。
3. 页面不显示“导师判断”或思考过程区域。
4. 模拟 internal policy 泄漏，前端收到 `MODEL_UNAVAILABLE`，数据库没有成功 Agent 消息。
5. 刷新页面，正文一致恢复。

## Rollback Points

- Provider adapter、decoder、API mapping、frontend rendering 分阶段提交检查，但在最终工作提交中保持跨层完整。
- 开发 feature flag 可回到旧自由文本路径用于定位回归；模型输出失败不能运行时 fallback。
- 如果 structured streaming 在某 provider 不兼容，任务应保持未完成并返回 `MODEL_UNAVAILABLE`，不能静默退回自由文本。

## Likely Files

- `aearn/services/api/app/services/conversations/learning_conversation.py`
- `aearn/services/api/app/agents/learning/learning_conversation_agent.py`
- `aearn/services/api/app/agents/runtime/sdk_runtime.py`
- `aearn/services/api/app/agents/runtime/guardrails.py`
- `aearn/services/api/app/services/llm/llm_client.py`
- `aearn/services/api/app/routes/learning_sessions.py`
- `aearn/services/api/tests/test_llm_integration.py`
- `aearn/services/api/tests/test_learning_sessions_m3.py`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx`
- `aearn/apps/desktop/src/stores/useAppStore.ts`
- `docs/architecture/api-contract.md`
- `docs/product/frontend-interaction-spec.md`
- `docs/qa/acceptance-test-plan.md`
