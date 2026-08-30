# Tutor 计划意图解析与 Runtime 流可靠性

## 目标

修复计划制定流程中两类会直接破坏用户完成学习计划的问题：一是服务端不能从学习者已明确表达的编程语言或学习方向中派生权威 planning intent，导致重复询问语言并固定展示全部课程；二是 Codex App Server 将正常长 reasoning 切成大量微小 delta 时，Aearn 按事件条数耗尽 2,000 条硬预算并错误终止 turn。最终效果是语言选择与课程候选由 Aearn 动态、可审计地收敛，Runtime 流按 item/phase 聚合和恢复，provider 分片粒度不再决定计划能否完成。

## 背景

- 当前 `language_courses` 只有语言、标题、描述、层级和 runtime profile，没有结构化的前端、后端、数据分析等课程意图 metadata。
- 当前语言问题 presentation 直接读取全部未归档课程；明确说“想学 Python”的用户仍会被再次询问，方向信息也不会缩小候选。
- 当前语言单选会默认选中第一项，截图中因此出现与用户意图无关的 C# 预选。
- 最新真实失败轮次以 `runtime_event_budget_exhausted` terminalize：三段 reasoning 共 1,989 个 delta，`aearn_learning_plan_draft` 完成后第三段 reasoning 在 sequence 2,000 被中断，session 保留全部 confirmed facts 但没有 draft。
- 已落地的 conversation-level Codex thread、owner-scoped runtime projection、commentary discard、terminal cleanup 和 completed-item authority 必须保持不变。

## 任务拆分

1. `08-21-planning-course-intent-dynamic-generated-ui`
   - 建立课程意图 taxonomy 与课程关联 metadata。
   - 明确语言自动确认；方向或多语言生成服务端 shortlist。
   - Generated UI 不再固定八项，也不默认选中第一项。
2. `08-21-reasoning-delta-coalescing-runtime-budget`
   - 对 reasoning/final-answer 微小 delta 做有界合并。
   - 删除 2,000 delta 业务失败条件，改用语义资源预算。
   - 完成跨 child 的真实计划流程、刷新、重启和历史验收。

## 范围内

- 仅覆盖 `plan_drafting + codex_sidecar_v1` 的 planning intent 与 raw Runtime stream。
- PostgreSQL 增加闭合学习意图 taxonomy 和课程-意图多对多关联。
- 精确语言别名继续复用 `LanguageCapability`，不从课程名称、标题或描述推断方向。
- 模型只可提出闭合 intent tag hint；Aearn 验证后仅用于 shortlist，不能直接确认 `language_id` 或定义课程。
- Runtime delta coalescing、source/projection sequence、字符/item/tool/time/内存预算与 snapshot recovery。
- Backend、Desktop、schema bootstrap、SSE、browser 和真实模型验收。

## 范围外

- 课程管理后台、自由创建课程、自动安装未支持 runtime。
- 将方向标签写成永久用户画像。
- 让模型直接写 planning fact、course ID、课程名称或 generated UI options。
- 全面改造非 `plan_drafting` Tutor/Harness 流。
- Remote compaction 或 provider 协议回退。

## 需求

### P0：Planning authority

- 唯一明确且有发布课程的语言必须以 `deterministic_input` confirmed fact 写入并跳过语言问题。
- 多个明确语言只展示这些语言对应的 active courses。
- 只有方向时，通过 PostgreSQL 课程意图 metadata shortlist；完全无信号时才展示完整发布目录。
- 语言与方向冲突时不得自动确认或默认选择，必须进入有限候选确认。
- 已 confirmed `language_id` 不得因模型建议或后续普通消息被静默覆盖。
- 新 active course 没有 intent tag 时，发布事务和 CI coverage gate 必须失败。

### P0：Runtime stream

- 连续同 `thread/turn/item/kind/channel/index/phase` delta 必须有界合并，不能跨 item、tool、compaction 或 terminal。
- provider 原始 delta 数不能作为正常 turn 的业务失败预算。
- Runtime reader、PostgreSQL projection 与 Desktop SSE 使用 projection sequence；审计保留 source range/count/hash，不保存 raw provider body。
- UI/SSE lag 触发 snapshot recovery，不得把模型 turn 标记为 unavailable。
- `item/completed` 继续作为终态文本校准 authority；commentary、reasoning summary 和 terminal discard 规则不变。

### P1：可运维性

- 记录 coalescing delta count、flush count、最大 pending bytes、projection latency 和 safe terminal code，不记录文本。
- 开发文档明确课程 metadata 发布规则、Runtime 预算和回滚路径。
- Feature gate 可分别关闭 intent resolution 与 delta coalescing，不跨 Runtime fallback。

## 验收标准

- [x] “我想学 Python 做数据分析”自动确认 Python，不出现语言选择 UI。
- [x] “我想学前端”只显示关联 frontend/web 的 active courses，且初始无选中项。
- [x] “Python 和 Go 哪个适合后端”只显示 Python 与 Go；模型不能代选。
- [x] 修改课程 title/description 不改变 intent shortlist；新增未标注 active course 使 bootstrap/CI 失败。
- [x] 5,000 个单字符 reasoning delta 可完成 turn，终态文本逐字一致，投影事件数显著低于 source delta 数。
- [x] `aearn_learning_plan_draft` repair 后继续 reasoning 不触发 `runtime_event_budget_exhausted`。
- [x] 慢 SSE/刷新/App Server restart 后通过 snapshot 恢复，不重复、不丢 completed reasoning/answer。
- [x] full pytest、Ruff、Mypy、Desktop tests/check、bootstrap twice、browser smoke 与 `git diff --check` 全部通过。

## 依赖与顺序

- 先实施 Child 1，建立动态课程候选和无默认选择的稳定交互契约。
- 再实施 Child 2，并使用 Child 1 的前端/Python/多语言场景完成长 reasoning 真实流程验收。
- Parent 只负责跨 child scope、验收矩阵和最终集成复核，不作为日常实现目标。
