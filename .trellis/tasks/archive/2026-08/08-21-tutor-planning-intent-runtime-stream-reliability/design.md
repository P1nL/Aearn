# 技术设计

## 1. 设计目标

建立两条互不越权但在 plan drafting 流程中衔接的服务端链路：`PlanningIntentResolver` 负责从 learner evidence 派生 confirmed language 或课程 shortlist；`RuntimeDeltaCoalescer` 负责把 provider 微小 delta 转换为有界、可恢复的 projection chunks。两条链路都不能把模型自由文本、reasoning 或 provider 分片当成领域 authority。

## 2. 总体数据流

```text
learner message
  -> deterministic language alias resolution
  -> closed intent-tag resolution / validated model hint
  -> confirmed language fact OR candidate course IDs
  -> durable typed request presentation
  -> learner selection
  -> confirmed language fact

App Server notifications
  -> item/phase-aware delta coalescer
  -> projection sequence + source range/count/hash
  -> PostgreSQL cumulative runtime text
  -> SSE chunk
  -> item/completed calibration
```

## 3. Authority 边界

- `language_courses`：课程身份、语言、层级、发布/归档状态。
- `LanguageCapability.aliases`：具体编程语言别名归一化。
- `tutor_learning_intents`：闭合方向 taxonomy。
- `language_course_intent_tags`：课程与方向的多对多关系及 rank。
- `tutor_planning_intake_facts`：confirmed planning facts。
- `tutor_interaction_requests`：某次问题的 durable presentation。
- Codex thread：自然对话、tool loop、reasoning/answer items；不能直接拥有上述领域状态。

## 4. 跨 child 契约

Child 1 输出：

```text
PlanningLanguageIntentV1(
  policy_version,
  explicit_language_ids,
  intent_tags,
  candidate_course_ids,
  resolution,
  reason_code
)
```

- `candidate_course_ids` 只能来自 active published course 与 taxonomy join。
- presentation 必须持久化 exact options，刷新后不得重新推断。
- `recommended=null` 时 Desktop 不选中任何 radio。

Child 2 输出：

```text
CoalescedRuntimeEvent(
  projection_sequence,
  source_sequence_start,
  source_sequence_end,
  source_delta_count,
  item identity,
  channel/index/phase,
  text chunk/hash
)
```

- 公共层只接收 Aearn item ID 与 projection sequence。
- raw external identity 保持 private/hash boundary。
- completed item 继续覆盖累计 projection 并完成校准。

## 5. 兼容与迁移

- Schema 全部 additive，bootstrap twice 幂等。
- 现有发布课程在 migration 中一次性 backfill intent tags；运行期不按 slug/title 匹配。
- Intent feature 关闭时回退完整发布目录，但仍不得默认选中第一项。
- Delta coalescing 关闭时可回退现有逐 delta projector，但新语义预算必须避免恢复 2,000 条正常流失败。
- 已确认 facts、已发 typed request、已完成 runtime text 不做 destructive rewrite。

## 6. 风险

- 方向分类误判：自动确认仅允许唯一明确语言；方向只影响 shortlist。
- Metadata 漏标：发布事务和 CI 双重 coverage gate。
- Coalescing 改变流式观感：使用 20–40ms/1–4KB 双阈值并做窄屏与慢流验收。
- Item 边界丢失：任何非同 key delta、tool、completed、terminal 都强制 flush。
- 同步 PostgreSQL 投影阻塞 worker：先通过 coalescing 降低调用数量，并记录 projection latency；如仍超阈值再拆异步 writer，不在首轮盲目并发同一连接。

## 7. 回滚

- 关闭 intent admission：保留 metadata 和已持久 typed requests，新问题使用完整目录。
- 关闭 coalescing：保留新 receipts/columns，恢复逐事件 projection，但不得恢复按 2,000 source delta terminalize。
- 出现 P0 时停止新的 Codex plan drafting admission，不删除 conversation thread、facts、draft 或 completed runtime projection。
