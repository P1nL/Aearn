# AGENTS.md

## 仓库概览

教学型仓库，包含 7 个**完全独立**的 Python 子项目，对应 YouTube/B站 教程视频。每个子目录是独立应用，**不共享依赖、不共享配置**。

## 关键规则

- **始终在对应子项目目录下**执行命令，绝不在仓库根目录操作（根目录没有 `requirements.txt`）
- **版本锁定非常重要**：各项目 README 中列出的是经过测试的版本。LangGraph / LangChain 跨版本不兼容，轻易升级会导致代码失效

## 子项目一览

| 目录 | 核心技术 | 额外依赖 |
|------|---------|---------|
| `01_ReActAgentAmapMCPServerTest` | LangGraph ReAct + 高德MCP | `langchain-mcp-adapters` |
| `02_ReActAgentHILTest` | ReAct + HIL 工具调用审查 | `langchain-mcp-adapters` |
| `03_ReActAgentMemoryTest` | 短期/长期记忆 + PostgreSQL | `langgraph-checkpoint-postgres` + Docker PostgreSQL |
| `04_ReActAgentHILApiTest` | FastAPI 后端 + Redis 会话 + HIL | PostgreSQL + Redis (Docker) |
| `05_ReActAgentHILApiMultiSessionTest` | 04 扩展：多会话管理、会话过期动态调整 | 同04 |
| `06_ReActAgentHILApiMultiSessionTaskTest` | 05 扩展：高并发异步 + Celery 任务队列 | 同04 + `celery==5.5.3` |
| `07_RefundApprovalAgent` | LangChain V1.x + LangGraph V1.x 闭环方案（**最新版本**） | 同04 |

## 安装依赖（按子项目）

项目 01~06 用旧版本栈：
```bash
pip install langgraph==0.4.5 langchain==0.3.25 langchain-openai==0.3.17
```

**项目 07 用全新版本栈（与01~06不兼容）：**
```bash
pip install langgraph==1.0.5 langchain==1.2.0 langchain-openai==1.1.6 \
  langgraph-checkpoint-postgres==3.0.2 rich==14.2.0 fastapi==0.128.0 \
  redis==7.1.0 concurrent-log-handler==0.9.28 uvicorn==0.40.0
```

## 启动服务

### 需要数据库的项目（03~07）

每个项目目录下各自有独立的 docker 配置：
```bash
# PostgreSQL（进入对应项目的 docker/postgresql 目录）
docker-compose up -d

# Redis（进入对应项目的 docker/redis 目录）
docker-compose up -d
```

- PostgreSQL: `postgres:15`，端口 `5432`，用户名/密码/DB 均为 `postgres`
- Redis: `redis:latest`，端口 `6379`
- 连接串：`postgresql://postgres:postgres@localhost:5432/postgres?sslmode=disable`

### 运行应用

项目 04~07 均为前后端分离，**必须按顺序启动**：

```bash
# 项目 06（有 Celery，需三步）
celery -A 01_backendServer.celery_app worker --loglevel=info
python 01_backendServer.py
python 02_frontendServer.py

# 项目 04、05、07（两步）
python 01_backendServer.py
python 02_frontendServer.py
```

- 后端默认端口：`8001`
- LLM_TYPE 配置位于各项目 `utils/config.py`，默认 `"openai"`，可改为 `"qwen"`（阿里通义）或 `"ollama"`（本地）
- 日志输出到 `logfile/app.log`（首次运行自动创建目录）

### 项目 01 运行方式

```bash
# 直接运行 MCP Server 脚本
python amapMCPServer.py
```

## 配置说明

所有需要数据库的项目配置集中在 `utils/config.py`，通过环境变量覆盖：
- `DB_URI`：PostgreSQL 连接串（默认已填好本地 Docker 地址）
- Redis 参数、LLM_TYPE、HOST/PORT 均为类属性，直接修改源码

## HIL 审查交互协议

项目 02~07 中 Human-in-the-Loop 的四种响应：
- `yes` — 接受工具调用
- `no` — 拒绝工具调用
- `edit` — 修改工具参数后调用（输入 JSON，如 `{"hotel_name": "全季酒店"}`）
- `response` — 不调用工具，直接给 Agent 反馈

## 注意事项

- 项目 07 的 `langgraph-checkpoint-postgres` 版本升至 `3.0.2`，项目 03~06 用 `2.0.21`，**两者不能混用**
- 项目 06 的 Celery broker 使用 Redis（同一个 Redis 实例，db=0）
- 前端用 `rich` 库实现终端交互，非 Web 界面
- `.claude/worktrees/` 是 OpenCode worktree 目录，忽略即可

<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->
