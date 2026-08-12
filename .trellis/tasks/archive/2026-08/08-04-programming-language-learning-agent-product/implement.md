# 编程语言教学 Agent 总体实施计划

## 启动时前置条件（已满足）

- 父任务在所有 child 完成前保持 `planning`；现在只进入跨 child 最终验收，不作为业务代码实现目标。
- 用户已明确批准并持续要求执行；11 个 child 已按依赖顺序完成。
- 每个 child 在启动前必须重新检查重叠 diff、补齐自身 planning artifact、验证 context 清单并加载 `trellis-before-dev`。
- 提交始终使用精确路径，不执行 reset、clean、大范围 stage、push 或 deploy；本机插件状态保持未提交。

## 实施波次

### 波次 1：基础权威状态

1. 完成 `08-04-learning-track-plan-mastery-domain`：track-scoped schema、repository、API contract、计划版本/迁移、mastery evidence 与 conversation/task scope。
2. 完成 `08-04-tutor-latest-input-teaching-relevance`：确保所有计划制定和教学 TurnRun 固定权威当前输入。
3. 两者通过后冻结 ID、version、task_kind、context source 和 error contract。

### 波次 2：创建与教学内容

4. 完成 `08-04-learning-home-plan-builder`：LearningTrack 首页和类型化计划制定闭环。
5. 完成 `08-04-lesson-document-authority-grounding`：标准/个性化/frozen LessonDocument、来源快照和质量门。

### 波次 3：练习与执行

6. 完成 `08-04-exercise-gates-execution-unlock`：Gate、模块诊断、attempt、execution tier、executor artifact migration 与服务端解锁。
7. 公开 composition 保持 container lock 缺失即 unavailable；开发 fixture 才启用 `teaching_local`。

### 波次 4：权威上下文事实

8. 完成 `08-12-tutor-authoritative-context-facts`：collecting typed facts、question state、统一 snapshot、语义选择、compaction barrier 和重复询问回归。
9. 冻结 facts/question/snapshot/selection receipt contract 后，Review、Action Runtime 和工作区才能继续。

### 波次 5：统一 Action Runtime

10. 完成 `08-12-tutor-controlled-action-runtime`：统一 grounding、plan drafting、runner execution 的 action lifecycle、resource policy、cancel/retry/verification/recovery 与 context feedback。
11. 迁移采用 shadow receipt，不复制 capability/effect/execution authority。

### 波次 6：适应性训练

12. 完成 `08-04-spaced-review-sessions`：显式依赖 authoritative facts，交付 track-scoped review queue、batch finalization 和 mastery 调度。
13. 完成 `08-04-model-code-review-exercises`：显式依赖 Action Runtime，交付 structured finding、false-positive scoring、private rubric 和预发布验证。

### 波次 7：工作区与上下文引用

14. 完成 `08-04-learning-workspace-context-references`：显式依赖 facts 与 Action Runtime，交付三栏 UI、typed references、action verification/recovery 状态和 scoped Tutor。

### 波次 8：集成收口

15. 完成 `08-04-learning-agent-integration-migration-qa-docs`：路由/导航迁移、旧 surface 审计、事实召回与 action authority 审计、核心语言矩阵、全量验证、source-of-truth 文档。
16. 最终 integration 只证明本地 code/fixture readiness，不代表发布、部署或 container fleet 批准。

## Child 启动原则

- 11 个 child 均已按显式依赖启动，没有用 parent/child 关系替代依赖检查。
- 每个 child 已独立 implement/check/finish/archive。
- 父任务当前只做跨 child 验收、任务工件收敛与归档。

## 全局验证命令

每个 child 运行聚焦命令；最终集成至少运行：

```powershell
uv --directory .\aearn\services\api lock --check
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\executor run python -m pytest -q
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-programming-language-learning-agent-product
git diff --check
```

数据库、executor 和 UI smoke 需要本地依赖可用；无法运行时记录精确阻塞，不用静态搜索替代。

## 高风险回滚点

- schema 仅 additive-first；回滚代码不删除新表或学习证据。
- `tutor_execution_intents` artifact reference migration 必须保留旧行兼容和 one-of FK；失败时关闭新练习执行，不 fallback 本机公开运行。
- Desktop 可通过 feature composition 回退到当前 Tutor workspace，但不得恢复旧 Graph 页面或绕过 cutover。
- Lesson/Plan version 已冻结后只能切换 active pointer，不能原地改写。

## 最终审查门

- 所有 PRD 验收项有测试、fixture 或明确人工 smoke。
- Python、JavaScript、TypeScript、SQL 各完成一条端到端核心链路。
- Java、HTML/CSS 扩展验证结果被单独标记；Go/C#/Rust/C++ 能力不被夸大。
- 没有隐藏 rubric、learner code、provider payload、reasoning、路径、命令或 secret 泄露。
- 当前 Tutor Harness、cutover、fresh TurnRun 与 safe projection 回归通过。


## 最终完成证据（2026-08-12）

- [x] 11/11 child 已独立归档。
- [x] API dependency lock、Ruff、Mypy 通过；全量 API 为 `515 passed, 1 skipped`。
- [x] 权威事实、Action、cutover、safe projection、review、integration 的串行聚焦批次为 `84 passed`。
- [x] executor dependency lock、Ruff、Mypy 通过；测试为 `11 passed`。
- [x] `pnpm --dir .\aearn desktop:check`、PostgreSQL `select 1`、Trellis validate 与 `git diff --check` 通过。
- [x] 浏览器检查覆盖 1440 三栏、1024 drawer、390 tabs、无水平溢出和零 console error。
- [x] 真实 provider smoke 与 reviewed container fleet 未执行；明确不构成发布、push、部署或生产迁移批准。
