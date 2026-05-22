# Backend SSE Streaming — Implementation Plan

## Phase 1: SSE 基础设施

### 1.1 创建 SSE 工具模块 `app/services/sse.py`

- [x] 实现 `sse_event(event_type, data)` — 格式化单个 SSE 帧
- [x] 实现 `sse_done(request_id, session_id, result_ref)` — 结束事件
- [x] 实现 `sse_error(error_code, message, recoverable)` — 错误事件
- [x] 实现 `wants_stream(request)` — Accept header 检测

### 1.2 改造 `llm_client.py` 支持流式输出

- [x] 新增 `complete_text_stream()` 方法，返回 `Generator[str, None, str]`
- [x] 提取 `_post_text_stream()` / `_iter_response_text_deltas()` — 逐帧 yield delta 而非拼接完整结果
- [x] 保留原有 `complete_json()` 不变（向后兼容）

验证：单元测试 mock LLM provider，验证 delta yield 正确

---

## Phase 2: Run 端点 SSE 化

### 2.1 修改 `app/routes/learning_sessions.py` run 端点

- [x] 在路由函数开头检查 `wants_stream(request)`
- [x] SSE 分支：创建 `run_exercise_stream()` async generator
- [x] 非 SSE 分支：保持原有 JSONResponse 逻辑不变
- [x] 错误处理：业务异常转为 `error` SSE 事件

验证：`curl -X POST -H "Accept: text/event-stream" .../run` 收到 SSE 事件序列

---

## Phase 3: Submit 端点 SSE 化

### 3.1 修改 `app/routes/learning_sessions.py` submit 端点

- [x] 在路由函数开头检查 `wants_stream(request)`
- [x] SSE 分支：创建 `submit_exercise_stream()` async generator
- [x] 发送 tool_status → runner_result → evaluation_result → done 事件序列
- [x] 非 SSE 分支：保持原有 JSONResponse 逻辑不变

验证：`curl -X POST -H "Accept: text/event-stream" .../submit` 收到 SSE 事件序列

---

## Phase 4: Agent-Draft 端点 SSE 化 + LLM 生成

### 4.1 改造 `app/services/note_repository.py`

- [x] 重命名 `_build_agent_draft()` → `_build_agent_draft_prompt()`（只构建 prompt）
- [x] 新增 `generate_agent_draft_stream()` — 调用 LLM 并 yield token deltas
- [x] 新增 `generate_agent_draft()` — 同步版本，调用 LLM 返回完整文本
- [x] 修改 `update_agent_draft()` — 调用 `generate_agent_draft()` 替代原有 prompt 拼接

### 4.2 修改 `app/routes/notes.py` agent-draft 端点

- [x] 在路由函数开头检查 `wants_stream(request)`
- [x] SSE 分支：创建 `agent_draft_stream()` async generator
- [x] 逐 token 发送 `agent_message` 事件
- [x] 生成完成后保存到数据库，发送 `done`
- [x] 非 SSE 分支：保持原有 JSONResponse 逻辑不变

验证：`curl -X POST -H "Accept: text/event-stream" .../agent-draft` 收到逐 token 事件

---

## Phase 5: 前端 useSSE 适配

### 5.1 改造 `useSSE.ts`

- [x] 从 `EventSource` 改为 `fetch` + `ReadableStream`
- [x] 实现 SSE 帧解析（按 `\n\n` 分帧，解析 `event:` / `data:` 行）
- [x] 支持 POST 方法 + request body
- [x] 自动添加 `Accept: text/event-stream` header

验证：前端 `desktop:check` 通过

---

## Phase 6: 集成验证

- [x] 后端所有现有测试通过（`pytest`）
- [x] 前端 `tsc && vite build` 通过
- [x] 自动 smoke test：run/submit/agent-draft 的 SSE 和 JSON 两种模式
- [x] 客户端断开连接时服务端不泄漏资源

## Actual Validation

- `uv --directory .\aearn\services\api run python -m pytest tests/test_health.py tests/test_llm_integration.py tests/test_onboarding_m2.py tests/test_learning_sessions_m3.py tests/test_reviews_m4.py tests/test_notes_m5.py tests/test_dashboard_resume_m6.py tests/test_worker_import.py tests/test_sse_utils.py` — 47 passed, 2 existing FastAPI deprecation warnings.
- `uv --directory .\aearn\services\api run ruff check app tests` — passed.
- `pnpm --dir .\aearn desktop:check` — passed.
- `uv --directory .\aearn\services\api run python -m mypy app` — still fails on existing typing issues in runtime/evaluation/review/dashboard repositories; no new SSE/LLM route files appear in the error list.

---

## Validation Commands

```bash
# 后端测试
cd aearn/services/api && python -m pytest

# 前端类型检查
pnpm --dir .\aearn desktop:check

# SSE 手动验证
curl -X POST http://127.0.0.1:8001/api/learning-sessions/{sid}/exercises/{eid}/run \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"code": "print(1)", "run_mode": "visible_tests", ...}'
```

## Risky Files

| 文件 | 风险 | 回滚策略 |
|------|------|----------|
| `app/services/llm_client.py` | 改造流式输出可能影响现有 `complete_json()` | 新增方法，不修改原有方法 |
| `app/routes/learning_sessions.py` | run/submit 是核心路径 | Accept header 分支，不影响默认 JSON 模式 |
| `app/services/note_repository.py` | agent-draft 改为真实 LLM 调用 | 保留 fallback 到 prompt 拼接 |

## Execution Order

Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6

Phase 2 和 Phase 3 可以并行开发（都依赖 Phase 1 的 SSE 工具模块）。
Phase 4 依赖 Phase 1 的 LLM 流式改造。
Phase 5 可以在 Phase 2 完成后开始（有真实 SSE 端点可测试）。
