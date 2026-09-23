# RAG 2.0 架构与离线演示讲解

> 这是阶段 I 的工程演示指南，不是第二份规格或上线许可。权威契约仍是[运行时架构](tutor-harness-runtime.md)、[数据库](database-schema.md)、[API](api-contract.md)与[验收计划](../qa/acceptance-test-plan.md)。演示只使用清晰标注的 synthetic fixture；“无需外网”仍要求本地 PostgreSQL。

## 1. 先说明问题，而不是只说用了向量检索

基础语言资料存在，不等于具体框架的课能教、题能做、代码能运行。把LangChain问题降成普通Python问题，或看到几条高相似度文本就宣称覆盖，都可能掩盖核心目标缺口。

本阶段把这些事实分开：主题身份、不可变资料版本、精确证据、facet覆盖、Lesson/题目/运行能力、公开发布权限。最终节点预检保留supported、partial、insufficient、unavailable，不让模型把缺口解释成成功。

## 2. 四条路线与六个生态

| 分组 | Subject | 当前边界 |
| --- | --- | --- |
| 路线 | route.python | shadow，非公开v2课程 |
| 路线 | route.typescript-javascript | shadow，JS/TS共用Subject但不增加公开课程 |
| 路线 | route.web-platform | shadow，HTML/CSS平台范围 |
| 路线 | route.sql | shadow，通用SQL不等于PostgreSQL执行环境 |
| 生态 | python.ai-applications | fixture_only；LangChain核心facet不能用Python基本语法替代 |
| 生态 | python.fastapi | fixture_only |
| 生态 | typescript.nodejs | fixture_only |
| 生态 | web.react | fixture_only |
| 生态 | web.platform | fixture_only |
| 生态 | sql.postgresql-foundations | fixture_only；PostgreSQL方言证据不等于可用沙箱 |

这些fixture只有确定性合成文本，不是下载的官方教程。既有公开课程列表未因本矩阵扩展。

## 3. 用一条链解释架构

```text
Subject registry（主题/能力/发布权限）
  -> 本地operator CLI（fixture reindex -> validate -> diff -> activate）
  -> immutable corpus + generation CAS + append-only events
  -> exact Subject/version/corpus范围内FTS
  -> 可选假embedding，异常/错scope回退FTS
  -> 有界证据选择 + facet/trust/diversity/budget CoverageReport
  -> 内部shadow预检与不可激活的迁移提案
  -> 显式内部Lesson/Tutor引用形状适配，不接公开consumer
```

Corpus active只代表该Subject的operator指针，不代表公开课程可选。数据库事务由调用方持有；演示发布会写自己的临时corpus表，预检/适配不得写学习轨道、进度、assignment或Lesson。

## 4. 三个可以现场解释的设计选择

1. **先限定证据范围，再排序。** Subject、版本、corpus、trust/facet是约束，不能检索后再用“语义相似”跨域补齐。假embedding只用于验证接口和降级，不代表真实向量质量。
2. **把缺口变成显式结果。** 核心目标不足时blocked/wait_for_release；可选节点的提案仍需未来显式确认，不能删空模块或破坏前置依赖。没有经过验证的替换目标就不生成replace_node。
3. **兼容形状不等于兼容权限。** 内部shadow可以检查旧Lesson/Tutor引用形状，但不能把v2 fixture伪装成旧v1 grounding行、真实HTTP来源或可持久化Lesson证据。

## 5. 如何增加未来生态

先在现有Subject/capability合同中注册并校验身份、语言、facet、trust与assessment；再为该生态准备版本化来源和验证证据，独立证明Lesson、题库、运行环境与发布许可。不能只加别名或更改release标签就公开。真实抓取、真实embedding、RagEvidenceBinding和逐scope消费者启用属于后续独立批准阶段。

## 6. 不应声称的结果

- 不声称真实官方文档已抓取/可用、真实embedding表现达标。
- 不声称框架沙箱、Docker隔离或实时运行健康已证明。
- 不声称既有用户计划已迁移、课程已公开或完整学习闭环已通过。
- 不把构建成功、静态无接线扫描或演示回放等同于生产发布许可。

## 7. 可重复命令

### 准备：独立空库，不是业务库

使用PowerShell 7及已有本地PostgreSQL。先单独创建本次操作人所有的空数据库，名字以 `aearn_rag260_cli_retrieval_` 开头；从可信本地配置向当前进程设置 `DATABASE_URL`，不要在录屏、日志或聊天中显示凭据。URL只允许本机主机及受限的 `sslmode=disable`、`connect_timeout` 查询参数；脚本会拒绝host/database/service等覆盖。

将 `$demoDb` 设为刚创建的实际库名；不要复用业务库或把已有库改名来满足前缀。脚本不会创建、bootstrap或删除库；启动前须按开发环境流程对这个隔离空库完成 `bootstrap_database()`，并核对连接的 `current_database()` 与 `$demoDb` 一致。

```powershell
# 从仓库根目录开始；DATABASE_URL已由可信本地配置设置，不要打印。
$demoDb = '<刚创建的aearn_rag260_cli_retrieval_前缀库名>'
$env:PYTHON_DOTENV_DISABLED = '1'
$env:LLM_TYPE = 'disabled'
$env:CODEX_RUNTIME_ENABLED = 'false'
$env:RAG_V2_ENABLED = 'false'
$env:RAG_V2_SHADOW_ENABLED = 'false'
$env:RAG_V2_OPTIONAL_EMBEDDING_ENABLED = 'false'

# 仅清除当前终端进程的libpq覆盖，不修改持久环境。
'PGSERVICE','PGSERVICEFILE','PGOPTIONS','PGHOST','PGHOSTADDR',
'PGDATABASE','PGPORT','PGPASSFILE','PGTARGETSESSIONATTRS' |
  ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }

uv --directory .\aearn\services\api run python ..\..\scripts\rag_v2_demo.py `
  --run-fixture-demo --confirm-disposable-db $demoDb

# 在同一个专有库重跑，验证确定性回放。
uv --directory .\aearn\services\api run python ..\..\scripts\rag_v2_demo.py `
  --run-fixture-demo --confirm-disposable-db $demoDb
```

这些 `RAG_V2_*` 环境值是演示的关闭态保护，不表示公开API新增了v2启用开关；内部adapter另有显式、默认false的调用参数。

### 预期输出与讲解顺序

- `ok=true`；10条Subject结果，4条 `release_state=shadow`、6条 `release_state=fixture_only`；合成材料与active fixture corpus分开标记，`public_course_admissible=false`。
- CLI实际执行reindex/validate/diff/activate；第二次同一idempotency keys回放，corpus/retrieval/coverage/preflight哈希不改变。
- FTS与facet coverage通过只代表合成范围；fake embedding有效输入可参与，错误hash/失败输入退回FTS，`real_provider=false`。
- `lc-overview`保留核心LangChain缺口，`activation_blocked=true`、`action=wait_for_release`，不替换成Python基本课程。
- 顶层 `public`、`real_source`、`real_embedding`、`live_runtime`、`learner_writes`、`deployment_approved` 全部为false。

缺少确认、库名/地址不匹配、连接覆盖或关闭态保护不满足时，输出安全错误码并非零退出。部分完成/外来corpus状态不会被自动修复、重置或删除。演示后由操作人确认无连接，再只删除本次创建的临时库。

### 数据库集成测试

使用另一个已bootstrap但没有demo已发布指针的专有测试库，将 `DATABASE_URL` 指向该库，并将 `RAG_V2_INTEGRATION_DB_CONFIRM` 设为精确库名；保留上述关闭态/无libpq覆盖条件。不要在已发布demo数据的库上运行依赖空active指针的旧测试。

```powershell
$env:RAG_V2_INTEGRATION_DB_CONFIRM = '<专有测试库精确名称>'
$env:AEARN_CORPUS_TEST_DATABASE_URL = $env:DATABASE_URL
uv --directory .\aearn\services\api run pytest -q tests/grounding `
  tests/learning/test_rag_grounding_adapters.py `
  tests/learning/test_rag_plan_preflight.py tests/learning/test_rag_plan_migration.py `
  tests/integration/test_rag_v2_architecture.py tests/database
```

未设置确认时集成测试会skip；skip不是验收通过。还需运行既有公开Lesson/Tutor/来源回归、全后端Ruff/Mypy及 `pnpm --dir .\aearn desktop:check`；完整执行结果以QA记录为准。
