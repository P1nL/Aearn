# Tutor 非文档型教学价值与条件式“继续”实施计划

## 实施前门槛

- 本任务是 complex task；`prd.md`、`design.md`、`implement.md` 经用户最终审阅后，只有后续明确批准才能运行 `task.py start`。
- inline 模式由主会话直接实施与检查，不派发 implement/check sub-agent。
- 开工前再次运行 `trellis-before-dev`，读取 backend/frontend spec index、`teaching-session-authority.md`、相关 source-of-truth 和本任务 research。
- 先检查 `git status` 与 scoped diff，不覆盖用户修改，不提交、不 push、不部署。
- 默认使用 fake/offline provider；真实 provider smoke 必须另行明确批准。

## 实施顺序

### 1. 冻结测试目标与旧版本不可变性

- 为 `tutor.lesson-teaching@1.0.0` 的 manifest、instruction 和 eval hashes 增加/保留不可变回归。
- 更新 focused test fixtures，先表达以下失败目标：
  - 新 Skill 缺少 v2 fields 被拒；
  - 少于两个或重复 `teaching_moves` 被拒；
  - response mode 与 dominant action 不匹配被拒；
  - Composer response state 不投影 Continue；
  - ordinary Continue 的重复 unit signature/hash 被拒；
  - empty shelf 不渲染 Desktop DOM。
- 旧 v1 parser/receipt/history case 继续可读。

### 2. 发布 `tutor.lesson-teaching@1.1.0`

- 新建 `aearn/services/api/app/agents/skills/tutor.lesson-teaching/1.1.0/`。
- 编写新的 `instructions.md`：职责边界、evidence-first、完整教学单元、两种以上 moves、理解检查策略、conditional Continue、`change_example` 例外和无价值时 pause。
- 扩充 `evals.json`：文档复述拒绝、HTML 找错、代码预测、误区纠正、learner feedback、micro transfer、continue strategy change、change-example same-purpose、no-useful-next pause。
- 计算并写入 exact content hashes，manifest 使用 `output_contract=tutor.teaching-step-decision.v2`。
- 更新 catalog order/hash tests，但不修改 `1.0.0` 文件。

### 3. 扩展 teaching-step provider/domain contract

- 在 `teaching_contracts.py` 增加闭合 `TeachingMove` 与 `TeachingLearnerResponseMode`。
- additive 扩展 `TeachingStepDecision` 和 `TutorProviderTeachingStepItem`：
  - `teaching_moves`；
  - `learner_response_mode`。
- parser 保留 legacy optional compatibility；selected `1.1.0` 由 gate 强制 v2 完整性。
- 更新 canonical teaching example、JSON Schema、replacement prompt 和 provider serializer exact Skill 版本。
- 更新 `InteractiveLearningCapabilityPolicyResolver` 和 `TeachingTutorDecisionGate` 选择/校验 `1.1.0`。
- Gate 校验 moves 数量/唯一性、response/action compatibility、change-example move 和 completion invariant。

### 4. 持久化 v2 unit receipt 与 recent-unit context

- 对 `080_lesson_teaching_practice.sql` 做 repeatable additive ALTER：
  - `teaching_moves_json`；
  - `learner_response_mode`；
  - v1/v2 schema/policy CHECK。
- 新 teaching commit 显式写 `teaching_action_receipt_v2` / `lesson_teaching_policy_v2`。
- 保持历史 v1 row 不改写；验证 bootstrap twice、append-only trigger、FK、reset/delete/cutover count。
- export 只 additive 返回 closed enums/mode，不返回 public message 或 protected body。
- `TeachingSessionRepository.teaching_context()` 加载最近最多四个 safe unit metadata。
- provider context/metadata 不写 raw message、prompt、reasoning 或完整 LessonDocument。

### 5. 实现非重复 Continue 与 checkpoint recommendation

- 在 Teaching gate 读取 exact stimulus control key 和 recent unit metadata。
- 对普通 `continue`：同 focus 的相同 action/moves/response signature 或相同 public-message hash 返回 `teaching_unit_not_advanced`。
- learner-message stimulus、new focus、changed strategy 和 explicit `change_example` 保持允许；不使用关键词或文本相似度启发式。
- reducer recommendation 优先级实现：completion/evidence/authority/session -> composer response -> conditional continue -> Free Reading policy。
- `build_teaching_action_shelf()` 仅在 `recommended_action_key=continue` 时投影 Continue。
- `respond_in_composer` 不投影 Continue primary；专用 pause/evidence/completion 控制不回归。

### 6. Desktop 条件渲染

- `ComposerActionShelf` 在无 server action 时返回 null，删除本地“继续阅读，或在 Composer 中提出问题”placeholder。
- 支持 secondary-only shelf，但 Composer 保持主要视觉路径。
- `TutorConversationSurface` 仅在有真实 descriptor 时添加 `has-action-shelf`。
- API parser 继续 exact 校验 `allowed_actions` 与 action arrays，不从 message/action 名称推断。
- 更新 component/API/Track workspace fixtures：
  - response state 无 Continue；
  - conditional Continue 可见且 CAS versions 正确；
  - empty shelf 无 DOM/overlay；
  - runtime/request/evidence/session/completion/Free Reading 优先级不回归。

### 7. 同步 source-of-truth 与 Trellis spec

- 更新 `docs/architecture/tutor-harness-runtime.md`：v1.1 Skill、教学单元 v2、recent-unit gate、one Turn invariant。
- 更新 `docs/architecture/api-contract.md`：Action Shelf 条件投影与 empty actions 语义；公开 API shape 若不变需明确 additive/no-bump。
- 更新 `docs/architecture/database-schema.md`：receipt v2 columns、legacy defaults、append-only。
- 更新 `docs/product/user-flows.md` 与 `docs/product/frontend-interaction-spec.md`：LessonDocument/Tutor 分工、Composer answer、非常驻 Continue。
- 更新 `docs/qa/acceptance-test-plan.md`：provider、PostgreSQL、Desktop 和浏览器矩阵。
- Phase 3.3 再判断是否把本次 pattern 写回 `.trellis/spec/backend/teaching-session-authority.md`、backend quality 与 frontend component/quality specs。

## 验证命令与证据

### 后端 focused

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/tutor/test_tutor_skill_catalog.py tests/tutor/test_tutor_provider_gateway.py tests/tutor/test_tutor_teaching_context.py tests/tutor/test_tutor_teaching_focus_reducer.py tests/tutor/test_tutor_teaching_action_loop.py tests/tutor/test_tutor_adaptive_teaching_evals.py tests/tutor/test_tutor_teaching_session_postgres.py tests/database/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\api lock --check
```

PostgreSQL/bootstrap-sensitive tests 串行运行；默认 fake provider，不读取真实 provider 配置。

### Desktop 自动化与浏览器

```powershell
pnpm --dir .\aearn\apps\desktop test
```

按当前 frontend quality gate，默认不运行 `pnpm --dir .\aearn desktop:check`，除非用户在实施或验收阶段明确要求额外 build/typecheck。

浏览器优先使用 `http://127.0.0.1:1420` + disposable fake API/provider，验证：

- HTML 教学单元一次完成解释/对比/找错设置；
- Composer-response state 没有 Continue；
- server conditional Continue 只在必要状态出现；
- empty shelf 不占 Composer 空间；
- `change_example`、pause、runtime、typed request、completion 不回归；
- 1440×900、900×900、390×844 无横向溢出，Composer 可触达，focus 可见；
- reduced motion、console error/warning、framework overlay 检查通过。

### 全量与 hygiene

若 focused 与浏览器通过，再运行串行完整 API pytest；随后：

```powershell
python .\.trellis\scripts\task.py validate .trellis/tasks/08-26-tutor-beyond-document-teaching-value
git diff --check
```

## 高风险与回滚点

1. **Skill version：** 绝不修改 `1.0.0`；hash 或 catalog 顺序异常时先回滚 policy selection，不伪造 hash。
2. **Provider schema：** v2 fields 对新 Skill 必须严格，对 legacy parser case 保持 bounded compatibility；不能让 optional 变成新运行时绕过。
3. **Receipt migration：** 只 additive ALTER，历史 v1 row 不 update；任何 CHECK/bootstrap 问题先回滚代码，保留列。
4. **Continue gate：** 只拒绝 exact same-focus signature/hash；禁止引入关键词、问号或相似度 heuristic 导致正常教学误拒。
5. **Action Shelf：** backend 是唯一 authority；Desktop 只消费 descriptor arrays，不能按 message 文本补按钮。
6. **交互体验：** 无 Continue 不等于无下一步；message 必须提供具体可回答任务，Composer 必须保持可见可用。
7. **验证边界：** fake/offline 证明 contract，不冒充真实模型教学质量或 release approval。

## 完成门

- PRD 的 AC1-AC10 均有代码或测试证据。
- 新 Skill、provider/domain、receipt/context、reducer/shelf、Desktop 和五份 source-of-truth 一致。
- 旧 Skill/historical v1 receipt 可读且未改写。
- focused、full API、Ruff、Mypy、lock、Desktop tests、浏览器三视口、Trellis validate 和 diff hygiene 通过，或对未执行项记录具体阻塞原因。
- 不调用真实 provider、不提交、不 push、不部署，除非用户后续单独明确批准相应动作。
