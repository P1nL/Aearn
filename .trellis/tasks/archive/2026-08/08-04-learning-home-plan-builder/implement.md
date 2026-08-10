# 学习首页与对话式计划制定实施计划

## 开始前置条件

- 只启动 `08-04-learning-home-plan-builder`，不启动产品父任务。
- 启动前重新运行 `git status --short --branch`、`git diff`、`git diff --cached` 和 child `task.py validate`；不得覆盖用户修改。
- 使用 `trellis-before-dev` 读取 backend、frontend、database、error、quality、state、type-safety 与 cross-layer 规范。
- 复用已完成的 LearningTrack、`plan_drafting` scope、fresh finite TurnRun、current-input、usage/cache、adaptive budget、summary/compaction 和 safe projection contract，不重新定义其语义。
- 默认使用 fake provider、fixed clock 与本地 PostgreSQL fixture；不执行真实 provider smoke。

## 有序实施清单

### 1. 冻结 planning contract 与语言目录

- 在 learning models/contracts 中增加 planning session、draft artifact、compact capability input、safe source summary 与 public response 类型。
- 增加 `/api/learning-tracks/catalog` 的服务端语言分类与 execution tier projection。
- 定义 stable error code、canonical draft hash、server-owned generator/policy version。
- 先写纯单元测试覆盖 compact JSON decode、长度边界、模块/节点数量、DAG、语言矩阵和敏感字段拒绝。

### 2. Additive schema 与 repository

- 新增 `tutor_learning_plan_sessions`、`tutor_learning_plan_drafts`、复合 FK、partial unique、source run/revision unique、CHECK、index、updated_at/append-only trigger。
- 更新 bootstrap、local user data delete/export/cutover target-state inventory，保证 user/session/draft/track 精确作用域。
- 实现 session create/current/read/cancel、draft append/replay、last safe error、confirm lock 与 pointer CAS。
- 使用真实 PostgreSQL 测试 bootstrap 两次、跨用户 FK、append-only、active-session unique 和 transaction rollback。

### 3. Planning service 与 API

- 新增 `LearningPlanSessionService` 和 verified-only routes。
- session create 原子创建专用 Tutor conversation 并绑定 `plan_drafting` broad scope；刷新通过 current/read API 恢复。
- confirm 复用现有 `LearningPlan` validation 和 `PostgresLearningTrackRepository.create_track`，同事务更新 session confirmed 状态。
- 添加 API idempotency、stale version/hash、already confirmed、cancelled、not found 与 safe error tests。

### 4. `learning.plan.draft` capability 与 exact Skill

- 在 capability catalog 注册 `learning.plan.draft@1.0.0`，不扩大通用 payload limits。
- 新增 `tutor.learning-plan-draft@1.0.0` manifest/instructions/evals，并更新精确 content hashes。
- 将 `CatalogCapabilityGateway` 重构为显式 handler dispatch，保持 unknown/default-deny；现有 grounding 行为与测试不变。
- Plan handler 解析 `profile_json` 与 `module_1..module_8`，执行质量门、registry source summary、server versioning 和 draft append/replay。
- 成功 safe result 只含 draft metadata；失败只写 allowlisted session error，不把完整 draft 放入 capability receipt/trace/event。

### 5. Task-aware policy、context 与 dispatcher

- 实现只对 active `plan_drafting` interactive run 授权 exact Skill/capability 的 policy resolver；general/track/proactive/default 路径保持拒绝。
- 为 planning context 注入 bounded session/current-draft source，不新增 context category、不复制 current input、不改变预算优先级。
- 在生产 interactive dispatcher 组合真实 catalog gateway；effect committer仍默认拒绝。
- 添加 run loop、decision gate、capability persistence、supersede/stale revision、current-input/history/budget/usage/cache/summary 回归。

### 6. Desktop 类型、API 与对话复用

- 为 language catalog、track list、planning session/draft、confirm/cancel 和 learning scope 增加严格 TypeScript 类型与 runtime guards。
- 移除 `TutorWorkspacePage` 与 general conversation 路由；保留 `TutorConversationSurface` 作为 planner 的唯一 history/SSE/composer/continuation 实现。
- API client 增加 LearningTrack/catalog/session endpoints，并让 planner ordinary input 显式发送 `plan_drafting` scope。
- 保持 local storage 只存允许的 shell/user 状态，不持久化草案、进度、tier 或 provider 信息。

### 7. Learning Home 与 Planner UI

- verified shell 默认渲染 `LearningHomePage`；实现 loading/error/empty 状态和三/二/一列响应式网格，添加卡直接创建/恢复 planner，不渲染语言目录。
- `LearningTrackCard` 只显示服务端字段，添加卡固定最后；continue/review 输出稳定 downstream intent 与真实未就绪提示。
- `LearningPlanBuilderPage` 实现 session resume/cancel；`TutorConversationSurface` 在 history ready 且无消息/run 时只显示中央 Composer，首条输入被接受后才进入无左侧栏/hero/外层卡片的 GPT 式 conversation 主列。进入 planner 即显示右缘展开/收起按钮并默认弹出与视口右缘留白、四角圆角的紧凑独立浮动 inspector；`current_draft` 为空时只渲染 emoji 占位，服务端返回草案后原位展示 typed plan route，不改变居中对话列宽度，同时保留修订自动重开、同版手动收起、刷新恢复和 confirm gate。
- 确认成功回首页、refetch 并突出新 track；stale draft/provider/quality error 保留 session 与可恢复操作。
- 不提供 general conversation / 对话历史页面或入口；既有服务端 conversation 数据与 API 保持兼容，不做删除。

### 8. 后端聚焦验证

按实现后的真实文件名运行至少：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_plan_sessions.py tests/test_learning_plan_draft_capability.py tests/test_learning_tracks.py tests/test_learning_track_repository.py tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_capability_gateway.py tests/test_tutor_run_loop.py tests/test_tutor_input_merge.py tests/test_tutor_context_builder.py tests/test_tutor_context_budget.py tests/test_tutor_provider_gateway.py tests/test_tutor_context_summary.py tests/test_tutor_conversation_history.py tests/test_tutor_sse.py -q
```

覆盖不可减少；若测试拆分为其他文件，记录替代命令。

### 9. 网页端浏览器 smoke

使用本地 API/fake fixture 启动 Vite 后，在 `http://127.0.0.1:1420`，在至少 1440px、900px、390px 三个 viewport 检查：

- 首页三/二/一列、添加卡末尾且点击直接进入 planner，不出现语言选择器；
- loading/error/empty、键盘 focus、主按钮与 live region；
- planner 无左侧栏、hero 和外层对话卡片；未激活时只有中央 Composer，首条消息/run 后切换为 GPT 式消息流与底部 Composer；进入 planner 即出现右缘按钮与四角圆角独立浮动窗口，`current_draft` 为空时窗口只有 emoji，输入栏聚焦前后外壳视觉不变化；服务端产生草案后同一窗口原位显示计划路线，可收起/重开且不挤占对话主列，并覆盖 refresh recovery、fresh run、草案版本更新自动展开、stale confirm、确认后高亮；
- 页面中不存在 general history / 对话历史入口，planner SSE 在离开页面时正确清理；
- `document.documentElement.scrollWidth <= clientWidth`。

不访问真实 provider；截图/记录不得包含用户真实对话、草案或密钥。

### 10. 文档与 release evidence

- 同步 user flows、frontend interaction、API、database、runtime、acceptance plan。
- 在 release readiness 记录 fake/API/DB/Desktop 证据、真实 provider 未执行、Lesson/Review/Workspace 未交付和“非发布批准”。
- 修正旧文档中 ordinary follow-up 复用 run 的过期描述。

### 11. 完整质量门

```powershell
uv --directory .\aearn\services\api lock --check
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-learning-home-plan-builder
git diff --check
```

API suite 串行运行。前端只使用网页端浏览器验证；除非用户明确要求，不运行 Desktop build/typecheck。PostgreSQL 或浏览器 smoke 无法执行时记录精确阻塞，不用 mock、静态搜索或 build 代替真实约束/交互检查。

### 12. Trellis 检查重点

- 首页 projection 是否完全 server-authoritative，添加卡是否始终最后。
- planning ordinary input 是否 fresh run，current input 是否 pinned 且不重复。
- exact Skill/capability 是否只在 active `plan_drafting` scope 开放，其他 scope 是否 default-deny。
- 通用 payload 上限、budget、usage/cache、repair attempt、summary/compaction 是否未被放宽或绕过。
- draft 是否 append-only，旧版本/stale hash 是否不可确认。
- confirm 是否原子、幂等且只创建一个 track/revision/route/scoped conversation。
- provider/quality failure 是否保留 session 且不 fallback 模板。
- raw prompt/history/provider body/reasoning/credential/执行目标是否未进入 receipt、trace、SSE、日志和 release evidence。
- fake evidence、real-provider 未执行、downstream 未交付和 release approval 是否明确区分。

## 预期文件范围

- `.trellis/tasks/08-04-learning-home-plan-builder/**`
- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/agents/harness/capabilities.py`
- `aearn/services/api/app/agents/skills/tutor.learning-plan-draft/1.0.0/**`
- `aearn/services/api/app/models/learning_tracks.py`
- `aearn/services/api/app/routes/learning_tracks.py`
- 可新增 `aearn/services/api/app/routes/learning_plan_sessions.py`
- `aearn/services/api/app/services/learning/**`
- `aearn/services/api/app/services/tutor/capability_gateway.py`
- `aearn/services/api/app/services/tutor/capability_policy.py`
- `aearn/services/api/app/services/tutor/interactive.py`
- `aearn/services/api/app/main.py`
- cutover/local user data inventory 与相关 tests
- `aearn/apps/desktop/src/App.tsx`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/styles.css`
- `aearn/apps/desktop/src/features/learning/**`
- `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx`
- 当前 source-of-truth 产品/架构/QA 文档

## 高风险回滚点

- schema/data 只增不删；代码回滚不清理 session/draft/track。
- capability/policy 可独立 fail closed；不得 fallback 模板或 general capability。
- Desktop 可回到旧 Tutor workspace 代码，但不得恢复旧 Graph/onboarding 或读取旧学习表。
- confirm transaction 若无法证明原子性，先关闭 confirm endpoint，不允许分步补写半成品。
- 不 reset、restore、clean 或覆盖用户已有修改。

## 启动前最终检查

- `prd.md`、`design.md`、`implement.md`、research 与 JSONL manifest 完整且为简体中文。
- `task.py validate` 通过。
- 用户已审阅本规划并明确批准开始实现。
