# 教学 Agent 集成迁移、QA 与文档

## 目标

完成各教学 child 与 Tutor Harness 的最终集成，收敛 conversation-first 导航、验证核心语言端到端矩阵、审计旧运行时隔离，并更新当前 source-of-truth 文档和 release-readiness 证据。

## 依赖

- 所有新产品 child 已完成。
- `08-04-tutor-context-governance-adaptive-budget` 及其五个 child 已完成。
- `08-12-tutor-authoritative-context-facts` 已完成。
- `08-12-tutor-controlled-action-runtime` 已完成。

## 需求

### R1 — 集成与导航收敛

- verified shell 默认进入 LearningTrack 首页，计划制定和学习工作区按新信息架构工作。
- 旧 general conversations 保持安全只读/次级入口；不得恢复旧 Graph/onboarding/learning/review 页面或 API。
- 所有 teaching task kind、context projection、Skill、capability/effect 和 public error contract 一致。

### R2 — 数据与迁移审计

- schema bootstrap 可重复，所有新表、FK/CHECK/unique/index、idempotency 和 cross-user/track scope 有真实 PostgreSQL 测试。
- 旧 `learning_*` 数据和 user-level Tutor plan 不被静默转换；文档明确显式导入/不迁移边界。
- cutover deletion/preservation inventory 纳入所有新增 Tutor 表，用户删除/重置语义与新领域一致。
- feature rollback 不删除新学习证据，也不绕过 cutover。

### R3 — 语言矩阵

- Python、JavaScript、TypeScript、SQL 各验证“计划 → Lesson → Gate → 反馈 → 持久化 → 复习证据”端到端 fixture。
- Java、HTML/CSS 作为扩展验证，失败不伪装成核心 MVP 通过。
- Go、C#、Rust、C++ 按实际 tier 清晰降级，无公开运行能力夸大。
- container image locks 缺失时，公开执行矩阵必须保持 unavailable；本机 runner 结果只标为 teaching_local。

### R4 — 安全与隐私

- 审计公共 API、SSE、Conversation、trace、checkpoint、activity/inbox、export 和 release evidence，不含 hidden tests、expected findings、reference answers、完整提交代码、provider body/reasoning、命令、路径、容器或 secret。
- stale/superseded TurnRun、artifact version 或 plan revision 不能写 Tutor 消息、attempt、evidence、unlock 或 effect。
- 真实 provider/container smoke 独立且可选，不替代确定性 contract 测试或发布批准。

### R5 — 上下文事实与 Action authority 审计

- 计划制定、Review、代码审核和右侧 Tutor 统一消费 `AuthoritativeContextSnapshot`，不得各自重新从 history 推断 confirmed facts。
- 已确认字段经过超过 recent history 上限的对话、summary 暂不可用、resume 和 replay 后不得被重复询问。
- grounding、plan drafting、runner execution 和模型代码审核验证 action 不存在双重 receipt/双重 terminal authority。
- action execution success 与 verification success 分列；未 verified 结果不能成为最终教学事实。
- context/action 指标进入 readiness evidence，但不泄露 raw prompt、历史、命令、路径、hidden test 或 private rubric。

### R6 — Source of Truth

- 更新 `docs/README.md`、runtime、user flows、frontend interaction、API、database、development/executor setup、acceptance 和 readiness ledger。
- 当前 docs 只描述已被代码和测试证明的行为；未开放能力明确标注 unavailable/deferred。
- 历史文档保留日期与历史状态，不改写为当前规范。

## 验收标准

- [x] 所有 child 的跨层 contract 和依赖已集成，无重复权威状态或旧 runtime caller。
- [x] 四种核心语言端到端 fixture 全部通过；扩展和降级语言结果真实记录。
- [x] API 全量 Pytest、Ruff、Mypy、executor tests、Desktop check、DB smoke 和 diff hygiene 通过。
- [x] cutover、fresh TurnRun、context governance、safe projection、idempotency 和 executor 生命周期无回归。
- [x] “30小时”等 confirmed intake fact 在长对话、summary 空缺和 resume/replay 场景不丢失、不重复询问，并有聚焦回归与事实召回指标。
- [x] grounding、plan drafting、runner execution、代码审核验证均通过统一 Action Runtime，且无双重业务 authority、重复副作用或未验证结果发布。
- [x] 所有 public/export/release surfaces 通过敏感字段审计。
- [x] source-of-truth docs 与实际 route/schema/test/config 一致，readiness ledger 明确不等于发布批准。
- [x] 任务树所有 child 独立 validate/archive，父任务最终只在跨 child 验收通过后归档。

## 范围外

- commit、push、deploy、生产数据迁移或发布批准，除非用户另行明确要求。
- 构建所有语言完整课程库或 reviewed container image fleet。
- 恢复任何已退休 Graph/router/SDK 产品运行时。
