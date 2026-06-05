# Aearn 前置环境配置

日期：2026-05-24
状态：Active V1.1
适用范围：当前 Aearn 第一版稳定基线和 post-MVP / v1.1 增强的本机开发环境、服务依赖、版本边界、运行顺序和验收命令

## 目标

本文件定义当前仓库可运行、可测试、可继续开发所需的本机环境。完成本文件后，开发者或开发 Agent 应能启动依赖服务、初始化数据库、运行 FastAPI、启动 desktop 前端，并执行最小验收命令。

历史教程目录已从当前工作树移除，不应继续作为最终应用目录或默认参考实现。正式实现固定在独立目录：

```text
aearn/
  apps/
    desktop/
  services/
    api/
    worker/
  packages/
    shared/
  infra/
    docker-compose.yml
```

## 前置决策

### 必须保留的当前输入

- `docs/`：产品、架构、API、数据库、前端交互和验收规格的 source of truth。
- `aearn/`：正式 runtime、桌面端、API、worker、共享包和本地基础设施。

### 不再保留

- 历史教程目录不进入当前仓库工作树。
- 历史教程代码不作为 Aearn runtime、测试夹具或默认实现来源。

## 本机工具链

### Windows 基础工具

| 工具 | 要求 | 用途 |
|---|---|---|
| PowerShell 7 | 建议安装 | 统一执行脚本、Docker、测试命令 |
| Git | 必需 | 版本控制 |
| Docker Desktop | 必需 | PostgreSQL、Redis、本地集成测试 |
| VS Build Tools / Visual Studio C++ Build Tools | Tauri 必需 | Windows 原生编译依赖 |
| WebView2 Runtime | Tauri 必需 | Windows 桌面壳运行 |

验证命令：

```powershell
pwsh --version
git --version
docker --version
docker compose version
```

### 前端与桌面端

| 工具 | 建议版本 | 用途 |
|---|---|---|
| Node.js | LTS，建议 20+ | React / Vite / 前端构建 |
| pnpm | 建议 9+ | 包管理 |
| Rust stable | stable channel | Tauri 编译 |
| Tauri CLI | 跟随项目 `package.json` 锁定 | 桌面端开发与构建 |

验证命令：

```powershell
node --version
corepack --version
pnpm --version
rustc --version
cargo --version
```

如果 `pnpm` 不可用：

```powershell
corepack enable
corepack prepare pnpm@latest --activate
```

### 后端与 Agent

| 工具 | 建议版本 | 用途 |
|---|---|---|
| Python | 3.11 或 3.12 | FastAPI、LangGraph、runner service |
| uv | 建议使用 | Python 依赖与虚拟环境管理 |
| LangChain | `1.2.0` | 当前第一版基线 |
| LangGraph | `1.0.5` | 当前第一版基线 |
| FastAPI | `0.128.0` | API 服务 |
| Redis client | `7.1.0` | session、Celery broker |
| Celery | `5.5.3` | FSRS 调度与异步任务 |

验证命令：

```powershell
python --version
uv --version
```

如果 `uv` 不可用：

```powershell
pip install uv
```

## 基础服务

第一版本地开发需要 PostgreSQL 和 Redis。

当前正式项目目录提供统一 compose 文件：

```text
aearn/infra/docker-compose.yml
```

建议服务：

| 服务 | 镜像 | 端口 | 用途 |
|---|---|---:|---|
| PostgreSQL | `postgres:15` | `5432` | 业务表、LangGraph checkpoint/store |
| Redis | `redis:latest` | `6379` | session、Celery broker、轻量锁 |

建议本地连接串：

```text
postgresql://postgres:postgres@localhost:5432/postgres?sslmode=disable
redis://localhost:6379/0
```

启动验证：

```powershell
docker compose -f .\aearn\infra\docker-compose.yml up -d
docker compose -f .\aearn\infra\docker-compose.yml ps
```

## 环境变量

正式项目提供 `aearn/.env.example`，本机复制为 `aearn/.env`。不要提交真实密钥。

```env
APP_ENV=development
API_HOST=127.0.0.1
API_PORT=8001

DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres?sslmode=disable
REDIS_URL=redis://localhost:6379/0

LLM_TYPE=openai
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
LLM_TIMEOUT_SECONDS=20
PLAN_GENERATION_ENABLED=true
EXA_API_KEY=

TZ=Asia/Shanghai
FSRS_SCHEDULER_VERSION=fsrs_v1_default
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

RUNNER_BROWSER_ENABLED=true
RUNNER_PYTHON_ENABLED=true
RUNNER_COMPILED_SANDBOX_ENABLED=false
```

### 官方 DeepSeek Chat Completions API

当前推荐的本机真实模型路径是官方 DeepSeek Chat Completions API。模型配置只从 `aearn/.env` 读取，不从桌面设置页或数据库读取。

```env
LLM_TYPE=deepseek
DEEPSEEK_API_KEY=<your-deepseek-api-key>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
LLM_TIMEOUT_SECONDS=60
```

配置说明：

- `DEEPSEEK_BASE_URL` 应填写官方 API root。后端会把 `https://api.deepseek.com`、`https://api.deepseek.com/v1` 或误填的 `/chat/completions` endpoint 归一到 `POST /chat/completions`。
- Direct JSON client 会发送 Chat Completions `messages`，并使用 `response_format={"type":"json_object"}` 约束 JSON 输出。
- Direct streaming client 会发送 `stream=true`，解析 `choices[].delta.content`，并把 `[DONE]` 作为终止帧处理。
- 动态学习路线生成会对 JSON completion 设置 `max_tokens=6000`，并保证该路径至少使用 60 秒超时；普通短 JSON/流式调用仍可按 `LLM_TIMEOUT_SECONDS` 控制。
- 真实 key 只写入本机 `aearn/.env`，不要提交到 Git。
- 未配置、配置不完整、模型超时、返回非法 JSON 或 schema 校验失败时，模型驱动接口返回 `MODEL_UNAVAILABLE`，不回退到确定性错因解释。
- 调用 `explain-error` 成功后可通过响应里的 `generation_source=llm` 验证模型链路；失败时看错误信封里的 `error.code=MODEL_UNAVAILABLE`。

### Legacy OpenAI-compatible Responses provider

旧的 `LLM_TYPE=openai` 路径仍保留给支持 Responses API 的 OpenAI-compatible provider。官方 DeepSeek 不走这条路径。

```env
LLM_TYPE=openai
OPENAI_API_KEY=<your-provider-api-key>
OPENAI_BASE_URL=https://<provider-host>
OPENAI_MODEL=<model-from-provider-model-list>
LLM_TIMEOUT_SECONDS=60
```

`OPENAI_BASE_URL` 会被归一到 `POST /v1/responses`。这条 legacy 路径仍要求流式 Responses 请求，后端会自动发送 `stream=true`，并使用 `text.format=json_object` 约束 JSON 输出；不要把它混用为官方 DeepSeek 配置。

### 动态学习路线生成

post-MVP 动态路线生成复用后端模型配置，并额外读取：

```env
PLAN_GENERATION_ENABLED=true
EXA_API_KEY=<optional-exa-api-key>
```

配置说明：

- `PLAN_GENERATION_ENABLED=false` 会关闭动态路线生成，直接回到第一版课程模板 / 已校验 onboarding plan candidate 路径。
- `EXA_API_KEY` 用于 `web_search` 工具。当前 `fetch_doc_toc` 和 `web_search` 作为同一组 web tools 注册；未配置 `EXA_API_KEY` 时，动态 agent 不能调用 web tools，应按 fallback 路径验证。
- 动态路线生成仍必须保留 `PlanDraft` 响应结构、runtime boundary 和 `source_attribution`；失败时不得向用户暴露 raw provider error、API key 或工具返回原文。
- 新语言公开支持不是只加权威文档 URL；还必须同步扩展 `Language` 枚举、数据库 CHECK、课程 catalog、runtime boundary、API 示例和验收用例。

常见失败签名：

- `400 Unsupported parameter: temperature`：`responses` 请求带了该模型不支持的参数；当前客户端不再传 `temperature`。
- `481`：API key 缺失、错误、过期或已撤销。
- `482`：余额不足或 key 独立额度已用尽。
- `483`：账号不可用，或 API key 未绑定对应能力分组。
- `429`：请求频率过高或当前并发较高。
- `503`：当前分组内暂无可用 provider。

## 依赖安装策略

### 后端

建议使用 `pyproject.toml` 固化依赖，不再沿用旧子项目各自的散装 `pip install`。

最低依赖集合：

```text
fastapi==0.128.0
uvicorn==0.40.0
langchain==1.2.0
langchain-openai==1.1.6
langgraph==1.0.5
langgraph-checkpoint-postgres==3.0.2
psycopg[binary,pool]
redis==7.1.0
celery==5.5.3
pydantic
python-dotenv
```

开发依赖建议：

```text
pytest
pytest-asyncio
httpx
ruff
mypy
```

### 前端

建议使用 Vite + React + TypeScript + Tauri，依赖以正式项目 `package.json` 为准。

最低能力：

- React 页面骨架
- API client
- SSE client
- 代码编辑器组件
- Tauri clipboard / file save / local config 能力

## 运行顺序

本地开发应按以下顺序启动：

```text
PostgreSQL / Redis
  -> schema bootstrap
  -> API server
  -> Celery worker
  -> Tauri desktop dev server
```

稳定启动脚本：

```powershell
.\aearn\scripts\start-dev.ps1
```

也可以通过 pnpm 调用：

```powershell
pnpm --dir .\aearn dev
pnpm --dir .\aearn dev:status
pnpm --dir .\aearn dev:restart
pnpm --dir .\aearn dev:stop
```

脚本会自动启动 Docker 依赖、执行 schema bootstrap、拉起 API、Celery worker 和 Tauri desktop dev server，并把日志写入 `aearn/.logs/`。Windows 下不要直接调用 `uvicorn` / `celery` 可执行脚本；应使用 `python -m uvicorn` / `python -m celery`，避免 `uv trampoline failed to canonicalize script path`。当前 worker 通过 API venv 启动，因为 API venv 包含 `redis` transport 和 editable worker 依赖。

`dev:status` 会显示 Docker 服务、API `/health`、desktop dev server 以及脚本追踪的进程状态。tracked PID 可能显示为 `alive`、`stale` 或 `untrusted`：`stale` 表示旧 PID 已不存在，`untrusted` 表示 PID 存在但命令行与 Aearn 启动命令不匹配。`dev:stop` 和 `dev:restart` 只会停止命令行已验证的 tracked Aearn 进程，遇到 stale/untrusted PID 会跳过并清理状态文件，避免误杀无关进程。

手动等价命令：

```powershell
docker compose -f .\aearn\infra\docker-compose.yml up -d
uv --directory .\aearn\services\api run python -m app.db.bootstrap
uv --directory .\aearn\services\api run python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
uv --directory .\aearn\services\api run python -m celery -A aearn_worker.worker_app:celery_app worker --loglevel=info --pool=solo
pnpm --dir .\aearn desktop:dev
```

## 前置验收清单

进入 Milestone 1 前必须满足：

- [ ] `docker compose ps` 显示 PostgreSQL 和 Redis 正常运行。
- [ ] 后端虚拟环境可安装并导入 `fastapi`、`langgraph`、`langchain`、`redis`、`celery`。
- [ ] 数据库连接串可连通。
- [ ] Redis 连接串可连通。
- [ ] Node、pnpm、Rust、Cargo 可用。
- [ ] Tauri 空应用能启动。
- [ ] `.env.example` 存在，真实 `.env` 未进入 Git。
- [ ] `docs/architecture/api-contract.md`、`docs/architecture/database-schema.md`、`docs/product/frontend-interaction-spec.md` 已作为开发输入。

## 不在前置阶段处理

- 不实现业务 API。
- 不写正式 Agent prompt。
- 不接真实 runner sandbox。
- 不做完整在线编译沙箱或项目级 compiled runner；Java / Go / C# 只允许本机 teaching-grade `managed_compiled_test` 单练习路径，C++ / Rust 暂不支持公开路线或真实编译运行。
- 不把历史教程目录重新引入正式项目。
- 不提交真实 API key、数据库密码或生产配置。

## 下一步

前置环境通过后，先跑最小本机 smoke：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_health.py tests/test_db_bootstrap.py
pnpm --dir .\aearn desktop:check
```

如果需要理解当前仓库，再阅读 `setup/newcomer-onboarding-guide.md`。如果要继续开发功能，按 `docs/README.md` 中列出的 source-of-truth 文档和 `plans/learning-agent-implementation-plan.md` 的审查顺序推进。
