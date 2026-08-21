# Reasoning delta 合并与 Runtime 预算修复

## 目标

修复 Codex App Server 将正常 reasoning/final answer 切成大量微小 delta 时，Aearn 因 2,000 条事件硬预算错误终止 plan drafting turn 的问题。引入 item/index/phase-aware 有界合并、source/projection sequence、语义资源预算和 lag/recovery 分层，使长 reasoning、tool repair、刷新和重启均不丢失终态 authority，也不因 provider 分片粒度产生 `model_unavailable`。

## 背景

- 当前 `CodexAppServerRuntime.run_turn()` 在 `len(collected) >= 2_000` 时抛出 `runtime_event_budget_exhausted`。
- 最新真实失败轮次产生三段 reasoning，共 1,989 个 delta；第二段 4,867 字符被切成 1,852 个 delta，draft tool 完成后第三段 reasoning 在 sequence 2,000 被中断。
- 该轮所有 planning facts 已 confirmed，session 保留但 draft count 为 0；terminal cleanup 正常。
- 已修复的 async subscriber backpressure、commentary correction、terminal discard 和 completed-item calibration 必须保留。
- `openai/codex` 的稳定方向是按 item/index 累积 delta、将 UI lag 与 turn 成功分离，而不是将每个微小 delta 当成业务预算单位。

## 范围内

- `plan_drafting + codex_sidecar_v1` reasoning/final-answer delta coalescing。
- source notification sequence 与 projection sequence 分离。
- receipt 增加安全 source range/count/hash，不保存 raw text/provider body。
- 删除 2,000 source delta 业务失败条件，增加 runaway、字符、item、tool、time、pending bytes 预算。
- PostgreSQL/SSE 降频、snapshot recovery、terminal flush 和 completed calibration。
- Celery heartbeat/projection latency 可观测性。
- 使用 Child 1 的语言/方向流程做完整 browser 集成验收。

## 范围外

- Remote compaction、provider fallback 或修改 `deepseek-v4-flash` 模型身份。
- 将 raw provider bytes/token IDs 持久化。
- 全面迁移 Harness/public-thinking stream。
- 通过简单把 2,000 改成更大的固定数字作为最终方案。
- 在首轮引入多个并发 DB writer 共享同一 psycopg connection。

## 需求

### P0：Delta coalescing

- 仅连续同 `thread_id/turn_id/item_id/event kind/channel/index/phase` delta 可合并。
- item、phase、summary/raw、tool、compaction、completed、terminal 边界必须 flush。
- 首轮建议 25ms 或 1,024 字符/4KB 任一阈值 flush；阈值配置有闭合范围和测试。
- 合并后文本逐字等于 source delta 串联，保留 whitespace 和 Unicode grapheme 内容。

### P0：Sequence 与 persistence

- raw/source sequence 用于内部顺序与审计；projection sequence 用于 receipt、DB/SSE reducer。
- 每个 coalesced event 记录 `source_sequence_start/end`、`source_delta_count`、content hash。
- 公共 DTO 不暴露 source/provider identity；Desktop 仍只消费 Aearn item ID 和 projection sequence。
- `item/completed` 全文继续原子校准累计 projection；text-less reasoning completion 保留累计文本。

### P0：预算与失败语义

- 正常 source delta 数不再导致 `runtime_event_budget_exhausted`。
- 保留极高 raw notification runaway guard，仅用于协议无限流/攻击，不得命中正常计划草拟。
- 预算按 item 数、tool 数、累计文本、turn 时长、pending bytes 和 projection lag 分离。
- SSE/Desktop lag 触发 discard/snapshot recovery 或 lag marker，不得杀死模型 turn。
- fence、identity conflict、malformed protocol、unsafe/oversized output 继续 fail closed。

### P1：性能与可观测性

- 普通日志只记录 source delta count、coalesced count、flush reason、最大 pending bytes、projection duration 和 safe code。
- 不记录 reasoning/final text、prompt、tool arguments、external IDs 或凭据。
- 真实长流验收不再出现与同步逐 delta projection相关的持续 heartbeat miss/drift。

## 验收标准

- [ ] 5,000 个单字符 reasoning delta 正常完成，最终文本逐字一致且 coalesced projection 数量有界。
- [ ] 交替 reasoning/tool/reasoning/final-answer 会在所有边界正确 flush，不跨 item/phase 混文。
- [ ] `aearn_learning_plan_draft` repair 后继续 reasoning 并重试成功，不出现 2,000-event unavailable。
- [ ] 慢 consumer、SSE gap、refresh、App Server restart 后 snapshot 恢复，无重复和永久 streaming row。
- [ ] interrupted/failed/unavailable terminal 清理 pending coalescer 和 streaming projection。
- [ ] completed reasoning/final answer 历史刷新逐字一致；commentary/summary 不公开。
- [ ] 使用 Child 1 的 Python 自动确认、前端 shortlist、多语言 shortlist 完成真实计划流程。
- [ ] full pytest、Ruff、Mypy、Desktop tests/check、browser smoke、`git diff --check` 通过。

## 依赖

- 依赖已归档的 `08-19-codex-thread-context-raw-runtime-stream` Runtime projection 基线。
- 逻辑实现可独立开始，但最终 browser 集成验收依赖 `08-21-planning-course-intent-dynamic-generated-ui` 已完成。
