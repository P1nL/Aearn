# Backend SSE Streaming — Technical Design

## Architecture Overview

```
┌─────────────┐     POST + Accept: text/event-stream     ┌──────────────────┐
│  Frontend   │ ──────────────────────────────────────────▶│  FastAPI Route   │
│  useSSE.ts  │ ◀── text/event-stream (chunked)  ─────────│  (StreamingResp) │
└─────────────┘                                           └────────┬─────────┘
                                                                   │
                                                          ┌────────▼─────────┐
                                                          │  SSE Emitter     │
                                                          │  (async gen)     │
                                                          └────────┬─────────┘
                                                                   │
                                              ┌────────────────────┼────────────────────┐
                                              │                    │                    │
                                     ┌────────▼───────┐  ┌────────▼───────┐  ┌────────▼───────┐
                                     │ RuntimeRunner  │  │ LLM Client     │  │ Repository     │
                                     │ (run/submit)   │  │ (agent-draft)  │  │ (DB ops)       │
                                     └────────────────┘  └────────────────┘  └────────────────┘
```

## Core Components

### 1. SSE Emitter Utility (`app/services/sse.py`)

统一的 SSE 事件发射工具，所有端点共用：

```python
import json
from collections.abc import AsyncGenerator
from typing import Any

async def sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a single SSE event frame."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"

async def sse_done(request_id: str, session_id: str, result_ref: dict) -> str:
    return await sse_event("done", {
        "request_id": request_id,
        "session_id": session_id,
        "result_ref": result_ref,
    })

async def sse_error(error_code: str, message: str, recoverable: bool = True) -> str:
    return await sse_event("error", {
        "error": {"code": error_code, "message": message, "recoverable": recoverable}
    })
```

### 2. Accept Header 路由分支

每个端点内部检查 Accept header 决定响应模式：

```python
from fastapi.responses import StreamingResponse

def wants_stream(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/event-stream" in accept

# 在路由函数中：
if wants_stream(request):
    return StreamingResponse(
        run_exercise_stream(...),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
# else: 原有 JSONResponse 逻辑不变
```

### 3. Run 端点 SSE 流

事件序列：`tool_status(running)` → `runner_result` → `done`

```python
async def run_exercise_stream(
    conn, session_id, exercise_id, payload, request_id
) -> AsyncGenerator[str, None]:
    yield await sse_event("tool_status", {
        "request_id": request_id,
        "session_id": session_id,
        "node": "runtime_runner",
        "tool": "run_exercise",
        "status": "running",
        "message": "正在运行代码...",
    })

    response, replayed = run_learning_session_exercise(conn, ...)
    conn.commit()

    yield await sse_event("runner_result", {
        "request_id": request_id,
        "session_id": session_id,
        "attempt_id": response["attempt_id"],
        "runtime_status": response["runtime_status"],
        "preview_url": response.get("preview_html"),
        "stdout": response["stdout"],
        "stderr": response["stderr"],
        "test_pass_rate": response["test_pass_rate"],
        "test_results": response["test_results"],
        "next_action": response["next_action"],
    })

    yield await sse_done(request_id, session_id, {"type": "run", "id": response["attempt_id"]})
```

### 4. Submit 端点 SSE 流

事件序列：`tool_status(running)` → `runner_result` → `tool_status(evaluating)` → `evaluation_result` → `done`

Submit 内部实际上先运行代码再评分，所以可以拆分为两个阶段发送事件。但当前 `submit_learning_session_exercise()` 是一个原子操作。

**设计决策**：不拆分 repository 函数，而是在 SSE 流中模拟两阶段：
- 发送 `tool_status(running)` 表示开始
- 调用 `submit_learning_session_exercise()` 完成全部逻辑
- 从返回值中提取 runner 部分发送 `evaluation_result`
- 发送 `done`

```python
async def submit_exercise_stream(
    conn, session_id, exercise_id, payload, request_id
) -> AsyncGenerator[str, None]:
    yield await sse_event("tool_status", {
        "request_id": request_id,
        "session_id": session_id,
        "node": "submit_pipeline",
        "tool": "submit_exercise",
        "status": "running",
        "message": "正在提交并评分...",
    })

    response, replayed = submit_learning_session_exercise(conn, ...)
    conn.commit()

    yield await sse_event("evaluation_result", {
        "request_id": request_id,
        "session_id": session_id,
        "attempt_id": response["attempt_id"],
        "code_completion_result": response["code_completion_result"],
    })

    yield await sse_done(request_id, session_id, {"type": "submit", "id": response["attempt_id"]})
```

### 5. Agent-Draft 端点 SSE 流 + 真实 LLM 生成

事件序列：`tool_status(generating)` → `agent_message` × N → `done`

**改造 `llm_client.py`**：新增 `complete_json_stream()` 方法，返回 generator 而非完整结果：

```python
def complete_json_stream(
    self,
    messages: Sequence[Mapping[str, str]],
    *,
    temperature: float = 0.2,
) -> Generator[str, None, str]:
    """Yield delta tokens as they arrive. Returns final full text."""
    # 复用现有 _post_json_stream 的 HTTP 请求逻辑
    # 但不在内部拼接完整结果，而是逐 delta yield
    ...
```

**改造 `_build_agent_draft()`**：从"拼接 prompt 字符串"改为"调用 LLM 并流式返回"：

```python
def generate_agent_draft_stream(
    conn, note, *, style, focus, session_id, attempt_id
) -> Generator[str, None, str]:
    """Yield token deltas. Returns final complete text."""
    prompt = _build_agent_draft_prompt(conn, note, ...)  # 原有 prompt 构建逻辑
    messages = [
        {"role": "system", "content": "你是一个编程学习笔记助手。"},
        {"role": "user", "content": prompt},
    ]
    client = OpenAICompatibleClient()
    return client.complete_json_stream(messages, temperature=0.3)
```

**路由层 SSE 流**：

```python
async def agent_draft_stream(
    conn, note_id, payload, request_id
) -> AsyncGenerator[str, None]:
    yield await sse_event("tool_status", {
        "request_id": request_id,
        "session_id": payload.source.session_id if payload.source else "",
        "node": "agent_draft",
        "tool": "llm_generate",
        "status": "running",
        "message": "Agent 正在生成笔记补全...",
    })

    session_id = payload.source.session_id if payload.source else ""
    full_text = ""
    for delta in generate_agent_draft_stream(conn, note, ...):
        full_text += delta
        yield await sse_event("agent_message", {
            "request_id": request_id,
            "session_id": session_id,
            "message_id": f"{note_id}-draft",
            "delta": delta,
            "content": full_text,
            "next_action": "continue",
        })

    # 保存完整结果到数据库
    _save_agent_draft_content(conn, note_id, full_text)
    conn.commit()

    yield await sse_done(request_id, session_id, {"type": "agent_draft", "id": note_id})
```

## Data Flow

### SSE 事件格式（与前端 `useSSE.ts` 对齐）

```
event: <event_type>
data: <json_payload>

```

每个事件以空行结尾。`event_type` 是以下之一：
- `agent_message`
- `tool_status`
- `runner_result`
- `evaluation_result`
- `done`
- `error`

### 错误处理

- 业务异常（EntityNotFound、StateConflict）→ 发送 `error` 事件后关闭流
- 未预期异常 → 发送通用 `error` 事件后关闭流
- 客户端断开 → generator 中捕获 `asyncio.CancelledError`，清理资源

### 向后兼容

- 不发送 `Accept: text/event-stream` 的请求 → 走原有 JSONResponse 路径，行为完全不变
- SSE 响应的最终数据与 JSON 响应内容一致（只是分步发送）

## Compatibility & Migration

- 前端 `useSSE.ts` 需要从 `EventSource` 改为 `fetch` + ReadableStream SSE 解析
- 改造量约 30 行，核心是 `TextDecoderStream` + 按 `\n\n` 分帧 + 按 `event:` / `data:` 解析
- 迁移期间前端可以不发 Accept header，继续使用 JSON 模式

## Important Trade-offs

1. **同步 DB 连接 + async generator**：当前 `connect()` 返回同步 psycopg 连接。在 async generator 中使用同步 DB 操作会阻塞事件循环。解决方案：使用 `asyncio.to_thread()` 包装同步操作，或在 generator 开始前完成所有 DB 操作。
2. **LLM 流式改造**：`llm_client.py` 使用 `urllib.request`（同步阻塞）。流式 pass-through 需要在线程中运行 HTTP 请求，通过 queue 或 generator 桥接到 async generator。
3. **幂等性**：SSE 流中如果客户端断开后重连，需要考虑是否支持 `Last-Event-ID`。当前设计不支持断点续传（每次重连重新执行），与 REST 行为一致。
