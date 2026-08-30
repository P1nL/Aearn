# 实施计划：Codex Runtime 持久上下文与原始运行流

## 实施前约束

- 当前任务保持 `planning`，用户审核最终规划后才能运行 `task.py start`。
- inline 模式：实现前加载 `trellis-before-dev`；实现后由主会话加载 `trellis-check`，不派发 implement/check sub-agent。
- 不覆盖 `.trellis/tasks/.obsidian/workspace.json` 等用户已有修改。
- 不调用真实 provider，除非到验证阶段再次获得明确批准。
- 不提交、不 push、不部署。

## 阶段 1：Schema 与持久契约

1. 新增 `tutor_conversation_runtime_threads`。
2. 调整 `tutor_run_runtime_bindings`：增加 conversation thread FK，解除 run-level thread unique，保留 turn unique 与兼容列。
3. 新增 `tutor_runtime_text_items`，建立 channel/state/sequence/hash/owner/FK/CHECK 约束。
4. 增加 immutable/state transition trigger、owner indexes、reset/delete 清理路径。
5. 编写 bootstrap twice、legacy binding backfill、owner-scope 和删除测试。

风险/回滚点：

- 先落 additive table/column，再切 dispatcher；任何约束调整必须证明旧行可读。
- 不删除旧 runtime receipt/binding；rollback 只停止新写路径。

## 阶段 2：Codex 配置与 Conversation Thread 生命周期

1. 从 shared exact capability 派生 `model_context_window=1_000_000` 与 `model_auto_compact_token_limit=616_000`。
2. 扩展 `CodexRuntimeConfig`/isolated config fingerprint 与测试。
3. 在 Runtime host/adapter 增加 `resume_thread`、manual compact 和 compaction lifecycle contract。
4. 重构 dispatcher：conversation get-or-create thread；每个 run 只 `turn/start`。
5. 实现 restart resume、single writer、generation fence、ambiguous legacy reseed 与 fail-closed unavailable。
6. 更新 binding/recovery tests，证明同 conversation 多 run 共用 thread、不同 turn。

## 阶段 3：Codex Item/Delta 规范化

1. 扩展 supervisor notification allowlist：reasoning delta/summary、agent message lifecycle、context compaction。
2. 扩展 adapter closed event union，保留 item kind、phase、private identity、sequence 和 completed text。
3. 严格路由：
   - reasoning text -> reasoning channel；
   - `agentMessage phase=final_answer` -> answer channel；
   - commentary -> nonpublic receipt；
   - summary -> 独立内部 channel，不冒充 raw reasoning。
4. 增加 duplicate/out-of-order/unknown phase/stale generation tests。

## 阶段 4：Durable Text Projection

1. 在 `runtime_projection.py` 增加 started/delta/completed/discard reducer。
2. delta 在 fence 与 sequence 校验后更新 `tutor_runtime_text_items`，并发布版本化 `turn_output`。
3. completed item 原子校准 text/hash/state。
4. final answer 完成后执行现有 teaching safety，并创建/校准正式 Tutor message。
5. reasoning completed 关联 run/message，支持历史读取；空 reasoning 不产生历史 Think。
6. 确保 receipt 只保存 hash/safe facts，不复制 raw text。
7. 覆盖 reset/delete、owner scope、terminal/stale/replay/partial recovery 测试。

## 阶段 5：Typed Planning Request 恢复

1. 扩展 planning context/tool contract，返回 exact confirmed facts、missing fields、fact/catalog version。
2. 缺失字段时由 Aearn tool handler 创建 durable `tutor_interaction_requests`，而不是让模型自由猜字段。
3. typed response 写 confirmed fact 后创建 fresh run；dispatcher resume 同一 thread。
4. 增加 Python -> 零基础 -> 学习目标回归测试，确保不再询问主题。
5. 增加 correction/reopen、version conflict、stale request 与 compaction 后 authority 重读测试。

## 阶段 6：Snapshot/SSE API

1. 定义 `tutor_conversation_snapshot_v3` 与 `tutor_runtime_item_stream_v1` closed models。
2. snapshot 加载 active reasoning/answer projection；timeline 加载 completed reasoning 与 final message 关联。
3. public serializer 只返回 Aearn IDs，移除 external IDs/provider metadata。
4. SSE 继续使用 opaque cursor/sequence；gap 或 mismatch 触发 snapshot recovery。
5. 保持 v2 read compatibility，更新 strict parser/source-guard tests。

## 阶段 7：Desktop UI

1. 更新 `types.ts`、`api.ts` 与 stream reducer，支持 reasoning/final-answer 双 channel。
2. 重构 `TutorConversationSurface.tsx`：同一 Tutor entry 内 Think 在上、answer 在下。
3. 使用小写 `think`、左边框、保留 whitespace；current 展开、history 折叠。
4. final answer delta 实时追加；completed 校准不闪烁、不重复。
5. commentary 不渲染；无 reasoning 的 terminal item 移除空 Think。
6. 保留 a11y、keyboard、reduced motion、scroll anchoring、responsive。
7. 更新组件、API parser、stream hook 和 grapheme tests。

## 阶段 8：Compaction 与端到端验收

1. fake App Server 模拟 pre-turn/mid-turn local compaction、manual compact、`contextCompaction` lifecycle。
2. 断言当前 custom provider 不发 remote compaction request。
3. 断言 compaction 后重新读取 server facts，继续 Python/零基础主线。
4. 运行 worker/App Server restart/resume 与 SSE reconnect/browser flow。
5. 更新 `docs/architecture/tutor-harness-runtime.md`、`api-contract.md`、`database-schema.md`、`frontend-interaction-spec.md`、setup/QA 文档，明确新契约与旧公开 reasoning 禁止规则的替代范围。

## 重点修改文件

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/agents/runtime/codex_config.py`
- `aearn/services/api/app/agents/runtime/codex_supervisor.py`
- `aearn/services/api/app/agents/runtime/codex_adapter.py`
- `aearn/services/api/app/services/tutor/codex_dispatcher.py`
- `aearn/services/api/app/services/tutor/runtime_projection.py`
- `aearn/services/api/app/services/tutor/conversation_contracts.py`
- `aearn/services/api/app/services/tutor/public_api.py`
- `aearn/services/api/app/services/learning/planning_facts.py`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/hooks/useTutorConversationStream.ts`
- `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx`
- 对应 backend/Desktop tests 与 source-of-truth docs。

## 验证命令

按改动阶段先运行 focused tests，再运行完整门禁：

```bash
uv --directory ./aearn/services/api run pytest   tests/test_codex_runtime_config.py   tests/test_codex_runtime_adapter.py   tests/test_codex_runtime_projection.py   tests/test_codex_plan_drafting_cutover.py   tests/test_tutor_conversation_runtime.py   tests/test_tutor_conversation_api.py   tests/test_db_bootstrap.py

uv --directory ./aearn/services/api run ruff check app tests
uv --directory ./aearn/services/api run mypy app
uv --directory ./aearn/services/api run pytest

pnpm --dir ./aearn/apps/desktop test -- --run
pnpm --dir ./aearn desktop:check

git diff --check
```

如实际测试文件名不同，先通过项目测试目录确认后使用最窄等价集合，不虚构成功结果。

## Browser 验收场景

- 1440×900、900×900、390×844。
- “我想学习 Python” -> “零基础” -> 只询问学习目标。
- reasoning 慢流、answer 慢流、burst、无 reasoning、commentary、interrupt。
- snapshot refresh、SSE reconnect、duplicate/gap、App Server restart。
- current Think 展开、history Think 折叠、键盘展开、无横向溢出和 console error。

## 完成门

- PRD、design、implement 与最终实现一致。
- P0/P1 验收全部有自动测试或明确 browser evidence。
- current DeepSeek 路径只使用 local compaction；无未经批准的 remote/provider 调用。
- schema bootstrap twice、完整 pytest、Ruff、Mypy、Desktop tests/check、browser smoke、`git diff --check` 全部通过。
- 运行 `trellis-check` 完成跨层复核；必要时更新 `.trellis/spec/`。
