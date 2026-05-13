# Aearn 前置环境配置

日期：2026-05-11  
状态：Draft V1  
适用范围：正式开发 `Aearn MVP` 前的本机开发环境、服务依赖、版本边界和验收命令

## 目标

本文件定义开始实施前必须准备好的开发环境。完成本文件后，开发者或开发 Agent 才应进入项目骨架、数据库 migration、API mock、前端联调和 Agent 状态机实现。

历史教程目录已从当前工作树移除，不应继续作为最终应用目录或默认参考实现。正式实现固定在独立目录：

```text
aearn/
  apps/
    desktop/
  services/
    api/
    worker/
  packages/
    shared-contracts/
  infra/
    docker/
  migrations/
  tests/
```

## 前置决策

### 必须保留的当前输入

- `docs/`：产品、架构、API、数据库、前端交互和验收规格的 source of truth。
- `aearn/`：正式 MVP runtime、桌面端、API、worker、共享包和本地基础设施。

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
| LangChain | `1.2.0` | 当前 MVP 基线 |
| LangGraph | `1.0.5` | 当前 MVP 基线 |
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

建议在正式项目目录提供统一 compose 文件：

```text
aearn/infra/docker/docker-compose.yml
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
docker compose -f .\infra\docker\docker-compose.yml up -d
docker compose -f .\infra\docker\docker-compose.yml ps
```

## 环境变量

正式项目应提供 `.env.example`，本机复制为 `.env`。不要提交真实密钥。

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

TZ=Asia/Shanghai
FSRS_SCHEDULER_VERSION=fsrs_v1_default
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

RUNNER_BROWSER_ENABLED=true
RUNNER_PYTHON_ENABLED=true
RUNNER_COMPILED_SANDBOX_ENABLED=false
```

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

完成项目骨架后，本地开发应按以下顺序启动：

```text
PostgreSQL / Redis
  -> Alembic migration
  -> API server
  -> Celery worker / beat
  -> Tauri desktop dev server
```

建议命令形态：

```powershell
docker compose -f .\infra\docker\docker-compose.yml up -d
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
uv run celery -A app.tasks.celery_app worker --loglevel=info
uv run celery -A app.tasks.celery_app beat --loglevel=info
pnpm --dir .\apps\desktop tauri dev
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
- 不做 Java / C++ 编译沙箱。
- 不把历史教程目录重新引入正式项目。
- 不提交真实 API key、数据库密码或生产配置。

## 下一步

前置环境通过后，进入 `Milestone 1：项目骨架与基础数据`：

1. 新建正式项目目录。
2. 建立 `apps/desktop` 和 `apps/api`。
3. 建立统一 Docker Compose。
4. 建立 `.env.example`。
5. 跑通 `GET /health`、数据库连接和桌面端调用后端。
