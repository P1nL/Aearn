# Backend SSE Streaming Implementation

## Goal

将后端关键长耗时端点从同步 JSON 响应改为 Server-Sent Events (SSE) 流式响应，使前端能实时展示中间状态（运行进度、Agent token 流、评分过程），提升用户感知性能和交互体验。

## Background

当前状态：
- FastAPI 0.128 + Uvicorn，所有端点同步返回 JSONResponse
- LLM 客户端（`llm_client.py`）已从 OpenAI 以 SSE 方式消费 token，但内部拼接完整后才返回
- 前端已完成 `useSSE` hook + SSE 事件类型定义（6 种事件类型），等待后端接入
- Celery/Redis 在依赖中但路由层未使用

目标端点：
1. `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run` — 代码运行
2. `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit` — 代码提交评分
3. `POST /api/notes/{note_id}/agent-draft` — Agent 辅助补全笔记

前端已定义的 SSE 事件类型：
- `agent_message` — LLM token 流
- `tool_status` — 工具/节点执行状态
- `runner_result` — 运行结果
- `evaluation_result` — 评分结果
- `done` — 流结束
- `error` — 错误

## Requirements

### R1：SSE 基础设施

- 选择 SSE 实现方案（FastAPI StreamingResponse vs sse-starlette）
- 定义统一的 SSE 事件格式，与前端 `useSSE.ts` 类型对齐
- 实现 SSE 响应工具函数，支持 event type + JSON data
- 处理客户端断开连接（graceful close）

### R2：Run 端点 SSE 化

- 运行开始时发送 `tool_status` 事件（status: running）
- 运行完成时发送 `runner_result` 事件
- 运行失败时发送 `error` 事件
- 最终发送 `done` 事件

### R3：Submit 端点 SSE 化

- 提交开始时发送 `tool_status` 事件
- 运行阶段发送 `runner_result` 事件
- 评分阶段发送 `evaluation_result` 事件
- 最终发送 `done` 事件

### R4：Agent-Draft 端点 SSE 化

- LLM 生成过程中逐 token 发送 `agent_message` 事件
- 生成完成后发送 `done` 事件
- 需要改造 `llm_client.py` 为 pass-through streaming

### R5：向后兼容

- 保留原有 JSON 响应能力（通过 Accept header 或 query param 切换）
- 前端可渐进式迁移，不强制一次性切换

## Confirmed Facts

- FastAPI `StreamingResponse` 原生支持 SSE
- `sse-starlette` 是 FastAPI 生态常用 SSE 库，提供更好的 EventSource 协议兼容
- 前端 `useSSE.ts` 使用浏览器原生 `EventSource` API
- `EventSource` 只支持 GET 请求；POST 端点需要用 `fetch` + `ReadableStream` 或改用 GET
- LLM 客户端 `_post_json_stream()` 已有 SSE 解析逻辑

## Constraints

- 不改变数据库 schema
- 不改变现有 API 路径（可新增参数）
- 保持与前端 `useSSE.ts` 事件类型定义一致
- 不引入 WebSocket（保持 SSE 单向流）

## Out of Scope

- 前端 `useSSE` hook 接入（已有独立任务）
- 实时协作/多用户广播
- 消息队列/Celery 任务化（当前规模不需要）

## Decisions

1. **SSE 触发方式：方案 A — POST + `text/event-stream` 响应**
   - 后端在现有 POST 端点直接返回 `StreamingResponse(media_type="text/event-stream")`
   - 前端 `useSSE.ts` 从 `EventSource` 改为 `fetch` + `ReadableStream` SSE 解析
   - 业界主流做法（ChatGPT、Claude API、Vercel AI SDK）

2. **Agent-draft LLM 生成：方案 A — 本任务一并实现真实 LLM 流式生成**
   - 改造 `_build_agent_draft()` 为真正调用 LLM（利用已有 `llm_client.py`）
   - 将 token 流 pass-through 给前端，实现逐 token 输出
   - `llm_client.py` 已有 SSE 消费逻辑，改造为 pass-through 增量工作量可控

3. **向后兼容策略：方案 A — Accept header 内容协商**
   - 客户端发送 `Accept: text/event-stream` 时返回 SSE 流
   - 否则返回传统 JSON 响应（默认行为不变）
   - 符合 HTTP 规范，不污染 URL，不影响 API 文档

## Open Questions

（已全部解决）

## Acceptance Criteria

- [x] Run 端点支持 SSE 流式响应，发送 tool_status → runner_result → done 事件序列
- [x] Submit 端点支持 SSE 流式响应，发送 tool_status → runner_result → evaluation_result → done 事件序列
- [x] Agent-draft 端点支持 SSE 流式响应，逐 token 发送 agent_message → done
- [x] 错误场景正确发送 error 事件
- [x] 客户端断开时服务端 graceful close，不泄漏资源
- [x] 原有 JSON 响应模式仍可用（向后兼容）
- [x] SSE 事件格式与前端 `useSSE.ts` 类型定义完全对齐
- [x] 所有现有测试通过
