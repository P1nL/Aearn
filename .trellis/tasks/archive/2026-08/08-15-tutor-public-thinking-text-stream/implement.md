# 实施计划

## 启动门

- 本任务当前只完成规划；必须在用户看到最新最终规划摘要后，用后续消息明确批准，才能运行 `task.py start`。
- Codex 使用 inline 模式，由主会话直接实施和检查，不派发 implement/check sub-agent。
- 实施前运行 `trellis-before-dev`，读取本任务 PRD/design/implement、backend/frontend specs、`docs/README.md` 路由出的 source-of-truth，以及当前 scoped `git diff`。
- 当前工作树已有 Tutor placeholder、布局、测试和文档未提交修改；先记录并 read-back，禁止 `git reset`、`git restore`、覆盖式重写或清理无关 `celerybeat-schedule.*` 文件。

## 实施顺序

### 1. 冻结新公开文本契约

- [x] 在 Harness contracts 中新增 `MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH=1280`，将 `TutorDecision`/`TutorRunResult` 改为 `public_thinking_text`，保持纯文本换行。
- [x] 将 provider schema 升级为 `tutor_provider_items_v4`，更新 canonical examples、prompt、schema hash、strict validation 和安全检查。
- [x] 新增 v3 fixture/legacy history兼容测试，但运行时不在 v4失败后回退 v3。
- [x] 更新所有 fake provider、eval fixture、context eval 与 test support，避免遗漏步骤数组消费者。

### 2. 实现 provider visible stream 与增量 projector

- [x] 为 `OpenAICompatibleClient.complete_json()` 增加通用 visible-output observer，不让 LLM 层依赖 Tutor。
- [x] Responses parser只转发 `response.output_text.delta`；reasoning、analysis和其他 output item继续忽略。
- [x] 为 transport retry 增加 restart callback；部分输出后的重试必须重置 generation。
- [x] 实现 `TutorProviderPublicTextProjector`，只解码 exact `message.public_thinking_text`，覆盖转义、Unicode、任意分片、字段重排、重复/非法字段。
- [x] 实现累计前缀安全 chunker；按句段/160字聚合，blocked时停止当前 stream并进入既有 repair。
- [x] 完整 JSON parse后比较 projector文本与 v4 field完全一致。

### 3. 建立 durable active-thinking authority

- [x] 在 `schema.sql` additive创建 `tutor_turn_public_thinking_streams`、复合FK/CHECK/index/updated trigger，并更新 bootstrap/cutover/reset inventory。
- [x] 为 `tutor_messages` 添加 `public_thinking_text`，保留 legacy JSONB；新增“不同时双写”约束。
- [x] 在 repository/lifecycle 添加 begin、append、complete、reset/discard、accept方法，每次短事务校验 lease/revision/decision/generation/foreground ownership。
- [x] 新增 `turn_output` event schema与identity规则，payload只允许 bounded文本、generation、operation、chunk sequence。
- [x] terminal/interaction-request/failed/interrupted/superseded路径原子 accept或discard stream；stale callback fail closed。

### 4. 升级 snapshot、event 与兼容投影

- [x] 将 snapshot/event/cursor版本升级到 v2，schema允许读取旧v1 rows但新cursor强制 fresh snapshot。
- [x] snapshot新增 exact `active_thinking`，只投影当前 active turn匹配的安全状态行。
- [x] snapshot v2 message使用 `public_thinking_text`；legacy steps以双换行只读合并。
- [x] 旧 `/history` 保持兼容，必要时将新文本投影为单元素 legacy steps，不删除旧字段/数据。
- [x] 更新 public service/routes/SSE tests，证明 stream endpoint仍只读 PostgreSQL、不调用 provider。

### 5. 重构 Desktop stream reducer 与 typewriter

- [x] 扩展 `types.ts` 与 `api.ts` exact parser：snapshot v2、active thinking、message text和 `turn_output` payload；extra/unknown/越界整体拒绝。
- [x] 修改 `useTutorConversationStream`：`turn_output`通过typed callback局部消费，其他事件继续节流refresh；重复/gap/reset仍走统一authority边界。
- [x] 新增 feature-owned live-thinking reducer和 grapheme typewriter hook；支持 snapshot hydrate、append/reset/complete/discard、conversation切换和 reduced motion。
- [x] answer只从成功snapshot获取；仅对刚完成的匹配turn执行逐字揭示，历史消息不重放。
- [x] 用fake timers验证每tick一个grapheme、emoji/组合字符不拆分、backlog顺序稳定和cleanup无悬挂timer。

### 6. 实现最终 `Think` 交互和样式

- [x] 无文本时渲染静态 `StateDot + Think`，不使用disabled `DisclosureRow`，无button/chevron/tab stop/helper copy。
- [x] append/incomplete snapshot只进入provisional buffer；同generation的validated `complete`与`350ms`稳定窗口同时满足后才切换为`DisclosureRow`，默认展开、无summary，正文为`white-space: pre-wrap`纯文本。
- [x] 移除“正在思考”“完成后会显示”、步骤数、footer和所有可见辅助说明。
- [x] final message通过turn identity接替live row，不重复DOM；answer逐字完成后自动折叠一次，之后尊重用户手动切换。
- [x] 历史message默认折叠；旧steps合并后同样不显示编号。
- [x] 融合现有`tutor-surface-root`高度修复和当前placeholder测试，不回退布局。

### 7. 同步 source-of-truth 与 Trellis spec

- [x] 更新`docs/architecture/tutor-harness-runtime.md`：v4 provider、visible projector、安全片段和final answer authority。
- [x] 更新`docs/architecture/api-contract.md`：snapshot/event v2、active thinking、turn_output、legacy compatibility和隐私边界。
- [x] 更新`docs/architecture/database-schema.md`：stream表、message text列、transaction/fence/cleanup。
- [x] 更新`docs/product/frontend-interaction-spec.md`：最终状态机、无辅助文案、逐字/reduced-motion/auto-collapse。
- [x] 更新`docs/qa/acceptance-test-plan.md`与`.trellis/spec/backend/database-guidelines.md`、frontend component/hook/type/quality guidelines。

## 验证计划

### 后端 focused tests

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_provider_gateway.py tests/test_tutor_run_loop.py tests/test_tutor_conversation_runtime.py tests/test_tutor_conversation_history.py tests/test_tutor_sse.py tests/test_tutor_routes.py tests/test_tutor_queue_control.py tests/test_db_bootstrap.py -q
```

重点断言：

- Responses delta任意分片、escaped JSON、Unicode和reasoning-only不泄漏；
- transport retry、repair、context rebuild、Steer revision、Interrupt、supersede和lease loss都产生正确reset/discard；
- cumulative safety跨chunk命中时不追加危险文本；
- stream row/event和terminal message transaction一致，stale callback不能写；
- snapshot reconnect恢复完整安全前缀，event重复/gap/cursor version行为正确；
- legacy steps读取与新text写入兼容，公共payload不含protected字段。

### 后端静态检查

```powershell
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api lock --check
```

### Desktop tests

```powershell
pnpm --dir .\aearn\apps\desktop test
pnpm --dir .\aearn desktop:check
```

重点断言：

- accepted后立即只有`● Think`，无button/chevron/helper text；
- 首delta只进入provisional buffer；超过`350ms`但未validated complete仍不进入DOM，两个条件满足后button才出现并默认展开；
- 每tick一个grapheme，换行保留，reduced motion直接同步；
- reset/discard/切换conversation清理队列；
- final message接替无重复，answer显示完后折叠一次，用户重开后snapshot refresh不再次折叠；
- legacy text无编号、无summary/footer；
- SSE unknown/extra/gap继续fail closed。

### 真实浏览器

使用 disposable fake provider/API，不调用真实模型和真实用户：

- 1440×900、900×900、390×844；
- 普通stream、慢stream、burst stream、repair reset、断线重连、Interrupt、success transition；
- 检查`scrollWidth <= clientWidth`、Composer可触达、visible focus、无overlay、console error/warning为0；
- reduced-motion下无逐字动画但折叠状态正确；
- DOM/network payload不含reasoning、prompt、provider body、diagnostic、secret。

### 最终 hygiene

```powershell
python .\.trellis\scripts\task.py validate .trellis/tasks/08-15-tutor-public-thinking-text-stream
git diff --check
```

同时检查 `.trellis/tasks/**` 无英文模板标题、占位内容、空描述或未解决问题。

## 高风险文件

- `aearn/services/api/app/services/llm/llm_client.py`
- `aearn/services/api/app/services/tutor/provider_gateway.py`
- `aearn/services/api/app/services/tutor/decision_protocol.py`
- `aearn/services/api/app/agents/harness/contracts.py`
- `aearn/services/api/app/services/tutor/run_loop.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/services/tutor/conversation_contracts.py`
- `aearn/services/api/app/db/schema.sql`
- `aearn/apps/desktop/src/hooks/useTutorConversationStream.ts`
- `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/styles.css`

## 回滚点

1. provider observer/projector可以关闭而不改变最终完整JSON parse；禁止回退到raw reasoning。
2. additive stream表/列可以保留，旧reader忽略；不执行破坏性DROP。
3. Desktop可回滚为active empty状态+最终message，但必须保留安全边界和当前高度修复。
4. 任一阶段发现必须改变Queue、typed request、effect/capability或global cutover语义时，停止实施并回到本任务重新规划审批。

## 完成门

- 后端、Desktop、文档和spec对`public_thinking_text`、v2 snapshot/event和legacy兼容一致。
- 所有自动化与浏览器矩阵通过，没有raw reasoning/provider信息泄漏。
- 当前工作树既有用户修改被保留并融合，无无关文件改动。
- 未经用户明确要求不提交、不推送、不部署。

## 实施结果（2026-08-15）

- Provider/Harness：`tutor_provider_items_v4`、visible-output observer、exact 增量 projector、累计安全分片与 final-text 一致性已落地；raw reasoning 路径保持隔离。
- PostgreSQL/API：`public_thinking_text`、`tutor_turn_public_thinking_streams`、snapshot/event/cursor v2、`turn_output`、message/request 原子 accept 与 legacy history 兼容已落地。
- Desktop：静态 `● Think`、provisional 文本离 DOM、validated `complete` + `350ms` 后默认展开、逐 grapheme、reset/discard、final reconciliation、回答完成后一次折叠、手动/键盘重开与 reduced motion 已落地。
- 后端完整串行 pytest：`582 passed, 1 skipped`；Ruff、Mypy、compileall、`uv lock --check` 通过。
- Desktop：Vitest `33 passed`；`pnpm --dir .\aearn desktop:check` 通过。
- Browser：Browser 插件完成真实流式交互、DOM、console、1440×900、900×900、390×844、reduced-motion 与无水平溢出验证；内置截图接口超时后，仅按仓库规范使用独立 Playwright 补充三张仓库外截图。
- Hygiene：`task.py validate` 与 `git diff --check` 通过；当日实施阶段未调用真实 provider、未部署、未修改生产数据、未提交或推送。

## 缺陷修复补充：计划 capability 终态无正式输出

- [x] 通过最新会话的 PostgreSQL `tutor_runs`、public thinking stream、Action receipt 和 plan session 定位到 `blocked_policy / capability_denied / action_adapter_failed`，确认不是前端折叠或逐字队列问题。
- [x] 在回滚事务中复现真实 provider payload：旧 `tutor.learning-plan-draft@1.0.0` 示例遗漏嵌套字段并使用 `goal` 别名，domain 原本应返回 `learning_plan_draft_invalid`。
- [x] 将 `LearningPlanDraftCapabilityError` 从 frozen dataclass 改为普通异常，避免事务 context manager 写入 traceback 时二次 `TypeError`；安全 session error 改为在失败事务回滚后记录。
- [x] 新增不可变 Skill `tutor.learning-plan-draft@1.0.1`，同步 exported capability field descriptions、policy resolver、source-of-truth 与回归测试。
- [x] capability 失败终态新增服务端安全正式消息，保留已完成公开思考文本，避免只显示 Think。
- [x] `retry` 仅新增 `blocked_policy + capability_denied` 与 `budget_exhausted + deadline_exhausted` 精确可恢复分支，允许旧契约失败或过期 deadline Turn 创建 fresh retry；其他 policy/budget denial 继续拒绝。
- [x] 使用新 Skill 做一次无数据库写入的真实 provider 结构校验：返回完整 8 个 profile 字段、4 个可解析模块和 4 个节点；未提交计划草稿或修改用户数据。
- [x] 修复 capability safe-result 二次 JSON 解码导致 `draft_id` 丢失的问题；Action adapter 现在直接保留 UUID/version/hash 并建立可验证 `plan_draft` authority。
- [x] 修复 fresh retry 跨 run 复用 context-summary curation key 的冲突；key 现包含 run/input identity，同 run high-water/terminal 仍去重。

- [x] 修复 `thread_turn_v2` 类型化请求只保存 composer/审批 item、未保存正式回答的问题；现在同一事务原子写入 Tutor 消息与请求 item，并按“正式回答 → 请求栏”排序。
- [x] 以 fresh retry 完整执行真实 Harness：run 正常 `completed`，计划 Action 为 `verified`，当前 plan session 指向 version 2 草稿；同时幂等回填该本地完成 run 缺失的正式消息，保留 pending approval。
- [x] 缺陷修复后的完整验证：后端 `590 passed, 1 skipped`，Ruff、Mypy、`uv lock --check` 通过；Desktop Vitest `35 passed`、生产构建通过；Trellis validate 与 `git diff --check` 通过。

## 收尾复核（2026-08-17）

- [x] 按最终实现与 source-of-truth 校准展示门：`turn_output append`、incomplete snapshot 和仅 timer 到期都不能进入 DOM；只有同 generation 的 validated `complete` 与首文本 `350ms` 稳定窗口同时满足后才启用 disclosure。
- [x] 核对工作提交 `fbe6e59c` 已覆盖 08-15 的 provider、Harness、PostgreSQL/API/SSE、Desktop、测试、文档与 Trellis spec；其后 `aearn/`、`docs/`、`.trellis/spec/` 无额外代码或规格漂移。
- [x] 最终完整验证证据：后端 `594 passed, 1 skipped`，Ruff、Mypy（173 个 source files）、`uv lock --check` 通过；Desktop Vitest `7 files / 41 tests`、`desktop:check` 与生产构建通过。
- [x] 08-16 后续任务已吸收计划确认入口合并、重复渲染与未完成思考短暂闪现的最终修复；08-15 的验收项与实现边界现已一致，可以归档。
- [x] 本次收尾只更新 Trellis 任务工件并执行归档/会话记录；未部署、未推送、未修改生产数据。
