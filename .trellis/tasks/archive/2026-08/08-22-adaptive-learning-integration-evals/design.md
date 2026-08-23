# 技术设计

## 1. Domain event adapter

为 Gate/Attempt、ReviewSession、progress 与 Lesson assignment 提供统一 adapter，输出 Child 1 定义的 `domain_event` stimulus：

```text
DomainTeachingEvent(
  kind,
  source_id,
  source_version,
  user_id,
  track_id,
  knowledge_key,
  teaching_session_id,
  safe_handles,
)
```

adapter 只读取现有 authority，不重算 score、mastery、review schedule 或 migration。事件 admission 使用唯一 source identity；重复事件返回已处理 receipt。

## 2. Structured teaching summary

在 checkpoint 基础上生成版本化 bounded summary：objective、resolved/active focus、unresolved questions、covered concepts、evidence handles、pause/completion、source checkpoint range/hash。summary append-only 或 predecessor-linked，旧版本只读。

context selection：

1. current session required checkpoint；
2. latest learner correction/current input；
3. exact Lesson/Gate/Review references；
4. bounded recent current-session messages；
5. current-session summary；
6. 明确引用或高相关的历史 session summary/reference；
7. learner memory/activity。

旧 summary source 失配时不进入 provider required facts；可同步重建或 fail closed 到恢复动作。

## 3. Evaluation harness

使用 fake provider scripts/fixtures 显式返回 closed teaching decisions，测试 Aearn validation/reducer，而不是用随机自然语言断言。为每个场景记录：input/stimulus sequence、expected legal actions、checkpoint transitions、provider call count、authority versions、public projection 与 forbidden markers。

教学质量 eval 允许多个合法路径，但检查不变量：先回答当前疑问、保留/显式改变主目标、不重复被拒内容、证据不足时澄清、避免固定流程话术、无 evidence 不推进。

## 4. Cross-layer fixture

使用 disposable local PostgreSQL + fake App Server/provider：

```text
verified user
-> active LearningTrack/plan/progress
-> active Lesson assignment/document
-> track-scoped Tutor conversation
-> teaching session + first unit
-> learner interruption / typed action
-> Gate or Review terminal event
-> completion pause / explicit next node
-> reload/reconnect
```

fixture 通过真实 service/repository/API/SSE/desktop parser 路径运行，不直接插入伪造完成/掌握结果。

## 5. Privacy 与治理

扩展 cutover exhaustive classification、scoped count、export/reset/delete tests。对 API/SSE/DOM/network/trace 做 key allowlist 与 protected-marker audit。有效 enum 中的普通单词不能被脆弱 substring 误杀；同时不得把完整 learner content/provider payload 写入日志作为测试证据。

## 6. 文档同步

更新：

- `docs/architecture/database-schema.md`：session/checkpoint/stimulus/run scope/summary；
- `docs/architecture/api-contract.md`：open/current/action/projection/conflict；
- `docs/architecture/tutor-harness-runtime.md`：三时间尺度、required context、single-step pause；
- `docs/product/frontend-interaction-spec.md`：mode swap、document follow、session grouping、Action Shelf；
- `docs/product/user-flows.md`：进入知识点、插问、自由阅读、completion、next node；
- `.trellis/spec/backend/**` 与 `.trellis/spec/frontend/**`：可执行 contract 和 QA gate。

`docs/README.md` 保持唯一索引，不新增平行总规格。

## 7. 回滚与非声明

若集成发现 P0，可关闭 new teaching admission 或 UI role swap，保留已持久化数据和旧读取路径。不得删除 checkpoint、回退为客户端 authority 或批量重写 conversation。最终本地通过只表示本地工程就绪，不表示真实 provider、部署、production migration 或 release 已批准。
