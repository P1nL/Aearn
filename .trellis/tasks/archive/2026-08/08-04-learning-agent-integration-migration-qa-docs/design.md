# 教学 Agent 最终集成技术设计

## 背景

本任务不再建立新的业务子系统，而是把已归档 child 的 LearningTrack、LessonDocument、Exercise Gate、模型代码审核、ReviewSession、权威事实、受控 Action Runtime 与三栏工作区作为一个整体进行最终审计。实现必须复用现有 PostgreSQL、service、API 和 Desktop 权威边界，禁止再引入第二套状态或旧 Graph/runtime caller。

## 设计目标

1. 用同一条确定性集成 fixture 证明 Python、JavaScript、TypeScript、SQL 的计划到复习证据闭环。
2. 把语言 capability、runtime catalog、image lock 与 execution tier 对账为真实能力，不把本地 runner 当作公开容器能力。
3. 让 cutover inventory 对 schema 中每张 `tutor_*` 表有显式分类，新增表未分类时测试失败。
4. 对齐当前导航、API、数据库、开发、executor、验收与 readiness 文档，并保留 dated history 的历史语义。
5. 使用已有专项测试证明 authoritative context、Action verification、stale fencing、safe projection 与 reset/export 无回归。

## 范围与边界

### 范围内

- `aearn/services/api/tests/test_learning_agent_integration_matrix.py` 的核心语言闭环与 tier 审计。
- `HarnessCutoverService` target inventory 的显式逐表分类和 schema reconciliation test。
- 当前 source-of-truth 文档的导航、命令与非声明收敛；带日期的新人导读保持历史快照。
- 最终全量 API、executor、Desktop、数据库、Trellis 与 diff hygiene 验证。

### 范围外

- 真实 provider 教学质量评估。
- 构建、签名、发布或批准 container image fleet。
- 恢复旧 onboarding、dashboard、learning session、top-level review、notes 或 Graph 页面/API。
- 静默转换旧 `learning_*` 或 user-level Tutor plan。
- push、deploy、生产数据迁移或发布批准。

## 数据流

### 核心语言闭环

```text
PostgreSQL user
  -> LearningTrack + active plan revision
  -> trusted grounding chunk + frozen source snapshot
  -> standard/personalized LessonDocument + active assignment
  -> server-owned Gate binding/state
  -> terminal submit result
  -> private submission + safe feedback + mastery/progress/schedule
  -> due ReviewSession
  -> warmup + terminal review Attempt
  -> exactly-once finalization + review evidence + schedule event
```

公开和开发 composition 使用同一 Gate/Review service。公开环境在 reviewed lock 缺失时保持 `unavailable`；测试注入的本地 runner 只产生 `teaching_local`，不写 executor health 或 image lock。

### Cutover 清单

```text
information_schema tutor_* tables
  == CUTOVER_TARGET_TUTOR_TABLES
   ∪ CUTOVER_SHARED_TUTOR_TABLES
```

user-owned target 表通过 user_id 或其 root FK 进行计数；shared allowlist 仅包含无 learner ownership 的 catalog、executor health、共享 immutable exercise/rubric 和 diagnostic version。任一新表若未分类，PostgreSQL 测试立即失败。

## 权威边界

- LearningTrack/plan/progress/mastery、Lesson assignment、Gate、Attempt、ReviewSession 和 Action receipt 均继续由现有 repository/service 拥有。
- 集成 fixture 只编排现有接口，不复制评分、解锁、调度或 tier 计算。
- public response 只递归审计敏感字段名和明确 marker；合法枚举如 `static_code_reasoning` 不被误判。
- `AuthoritativeContextSnapshot` 与 confirmed intake facts 继续由现有 planning/review/context tests 覆盖；最终任务不从 history 重算。
- execution success 与 Action verification success 分列；只有 verified/current receipt 可以成为可发布事实。

## 兼容、迁移与回滚

- schema 仍为 additive/repeatable bootstrap；本任务不新增数据迁移脚本。
- 旧数据只参与 exact cutover inventory/deletion，不转换成新领域数据。
- ordinary reset/delete 按 child-to-root 清理 user-owned 当前状态；共享 immutable catalog/exercise 保留。
- 代码回滚不删除新学习证据、不恢复旧路由、不绕过 `harness_cutovers`。
- 文档中的早期 dated sections 标记为历史截面；当前段落追加在后，不篡改历史证据。

## 隐私与安全

公共 API、SSE、history、public process、trace/checkpoint safe projection、activity/inbox、export 与 release evidence 禁止完整 submission、hidden tests、reference answer/private rubric、raw provider body/reasoning、命令、路径、容器或 secret。测试数据只使用事务回滚的本地 fixture，不调用真实 provider、Docker 或生产数据。

## 风险

- 集成 fixture 可能误把测试注入的 runner 当作真实执行；通过明确断言 `teaching_local` 和 public `unavailable` 防止。
- cutover inventory 使用 descendant join，若未来 FK 改动可能计数错误；schema reconciliation 只能保证分类完整，相关业务测试仍需验证 scope。
- 文档历史段落可能与当前段落并存；通过显式“历史截面”提示和 `docs/README.md` source-of-truth 索引降低误读。
- PostgreSQL bootstrap-heavy tests 不能并行；最终命令保持串行。
