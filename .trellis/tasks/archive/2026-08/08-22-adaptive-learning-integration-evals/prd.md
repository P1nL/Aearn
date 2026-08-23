# 长期自适应教学集成、评估与文档

## 目标

在前三个 child 的 durable authority、closed teaching Loop 与 Desktop 工作区之上完成 Gate/Attempt、ReviewSession、Lesson migration、progress/mastery 与长期上下文的端到端集成，建立可重复的 deterministic eval、隐私/迁移/恢复门，并把最终 contract 写回 source-of-truth 文档与 Trellis spec。

## 依赖与顺序

- 必须在前三个 child 全部完成、提交、归档后启动。
- 本 child 是父任务的最终实现与集成验收 child。

## 范围内

1. Gate/Attempt、ReviewSession、progress、assignment/migration terminal domain-event admission。
2. structured teaching summary、跨 session exact reference/retrieval 与压缩保护。
3. 长期恢复、连续追问、纠正、自由阅读、completion 与 stale fencing eval。
4. PostgreSQL bootstrap twice、cutover exhaustive inventory、export/reset/delete/privacy。
5. backend full tests、Ruff、Mypy、Desktop tests/check、browser smoke、Trellis validate、diff hygiene。
6. `docs/README.md` 所列 source of truth 与 `.trellis/spec/**` 更新。

## 范围外

1. 新增与父任务无关的教学功能、课程内容生成或路线规划。
2. 重写前三个 child 已冻结的 public contract，除非集成测试发现 P0 缺陷并同步更新其 docs。
3. 真实 provider、部署、push、生产数据迁移或公开发布。
4. 通过阅读时长、滚动、聊天正文或模型主观判断写 mastery。

## 需求

### R1 — Domain event 集成

- Gate/Attempt terminal、Review finalization、progress completion、assignment migration/conflict 使用 durable source ID/version 触发至多一次教学 Turn。
- 事件只能携带 learner-safe handles，hidden tests/rubric/submission/provider data 不进入 prompt、trace 或 public projection。
- stale/重复事件幂等忽略；authority conflict 进入 `authority_pause` 和可恢复 Action Shelf。

### R2 — 长期上下文与压缩

- current stimulus、current session focus/objective、最新纠正与 exact authority 优先于旧 session summary/memory。
- 每个 teaching session 生成 bounded structured summary，保留 source IDs/hashes、unresolved questions、covered concepts 与 completion/pause 语义。
- 压缩不得退休 active focus、被暂停主线、最新纠正、未解决问题或唯一 evidence。
- 跨 knowledge 默认只选相关 frozen summary/reference，不全量重放长期 conversation；用户明确引用旧 session 时可精确检索。
- source/version 失配使 summary stale，并触发重建或 fail-closed recovery。

### R3 — Deterministic eval

至少覆盖：

- 首个单步教学后停止；
- 连续多类型追问并返回/调整主线；
- 用户纠正覆盖旧 focus；
- free reading 往返与显式 escalation；
- Gate/Review evidence 更新；
- Lesson migration conflict；
- completed 停留与显式 next node；
- 跨日刷新/reconnect/restart；
- summary stale、provider unavailable、stale/superseded Turn；
- 不同 learner response 产生不同合法 action path；
- 无 trusted evidence 时拒绝 mastery/自动推进。

### R4 — 集成与隐私门

- 全部新 `tutor_*` 表在 cutover target/shared 集合中穷尽且互斥。
- local export/reset/delete 包含 teaching state，公开 payload 省略 protected data。
- API/SSE/DOM/network/trace 不出现 prompt、reasoning、provider body、完整问题/提交、hidden test/rubric、命令、路径或 secrets。
- schema bootstrap twice 与 child-to-root cleanup 通过。

### R5 — 文档与运行边界

- 更新 database、API、Harness runtime、frontend interaction、user flows、setup/QA 与 Trellis specs。
- 文档明确默认 fake provider、本地 PostgreSQL、single-step pause、mode swap、Action Shelf 与 explicit next-node authority。
- 不创建重复 source of truth，不恢复旧 learning session/Graph 页面。

## 验收标准

- [ ] Gate/Review/progress/assignment 每个 durable terminal event 最多触发一次 bounded Turn，重复/陈旧事件不重复输出或写状态。
- [ ] 跨日恢复仍准确恢复 mode、focus stack、未解决问题、assignment fence 与 Action Shelf。
- [ ] 压缩后 active objective、暂停主线、最新纠正和必要 evidence 均保留；旧 summary 不覆盖新输入。
- [ ] 明确引用历史 session 时 context 能取得 exact bounded reference；默认不全量重放长期 conversation。
- [ ] deterministic eval 证明教学路径可变化但始终 closed、可恢复、单步停止。
- [ ] 没有 trusted evidence 时不会完成、解锁或推进下一知识点。
- [ ] exhaustive cutover、bootstrap twice、export/reset/delete/privacy tests 通过。
- [ ] focused/full Pytest、Ruff、Mypy、Desktop Vitest/check、三视口 browser smoke、Trellis validate 与 `git diff --check` 全部通过。
- [ ] source-of-truth docs/spec 与最终实现一致，无重复规格。
- [ ] 默认未调用真实 provider，未 push、部署或修改生产数据。

## 风险与控制

1. **集成测试重新实现 authority**：fixtures 必须调用现有 repository/service，不在测试中计算 score/unlock/schedule。
2. **长上下文膨胀**：结构化 summary + relevance selection + protected set，不默认全量历史。
3. **领域事件重复触发**：source identity、idempotency 与 run/session version fence。
4. **文档漂移**：先更新 source of truth，再更新索引/规格引用，并用 grep/contract tests检查旧术语。
