# Codex Sidecar 集成验收证据

**日期：** 2026-08-18
**任务：** `08-17-codex-sidecar-integration-qa-docs`
**结论：** 本地集成通过；不是 production/release approval。

## 支持矩阵

| 区域 | 已验证 | 非声明 |
| --- | --- | --- |
| Windows transport | stdio JSON-RPC、strict config、initialize/thread/turn/tool/interrupt/shutdown | 不支持 Windows daemon、WebSocket 或远程 transport |
| Provider | exact `deepseek-v4-flash` + `aearn_deepseek` + Responses | 不支持 OpenAI、其他 DeepSeek、Chat Completions 或 fallback |
| Runtime ownership | isolated Home、single process/file-lock owner、generation fence、child crash recovery | 不捆绑/安装/升级 Codex，不使用全局 Codex Home |
| Domain tools | typed context/draft、repair、awaiting user、conflict、policy、fatal、timeout、duplicate replay | Codex 不能 confirm LearningPlan 或创建 LearningTrack |
| Persistence/public | immutable Runtime kind、private binding、append-only receipt、safe final/error、SSE/history redaction | 不公开 reasoning、raw tool/provider body 或 external IDs |
| Product cutover | 仅全新 `plan_drafting`；Harness scope isolation；steer/interrupt；same-Runtime Retry | 不代表所有 Tutor scope 已切换 |

## 自动化证据

| Gate | 结果 |
| --- | --- |
| Codex protocol/Runtime/domain/projection/cutover focused matrix | `66 passed in 16.91s`，排除 `real_provider` marker |
| Public/SSE/history/redaction focused matrix | `21 passed in 10.70s` |
| 完整 API suite | `660 passed, 2 skipped in 145.57s`；skips 为 opt-in real-provider cases |
| Ruff | `ruff check app tests ../worker/aearn_worker` 通过 |
| Mypy | `192 source files` 通过 |
| compileall / lock | 通过；lock 解析 `54 packages` |
| PostgreSQL | bootstrap 连续两次通过；shared/target cutover inventory 通过 |
| Desktop | `tsc && vite build` 通过，84 modules transformed |
| process leak | `codex_sidecar_process_count=0` |
| credential literal scan | credential/private-key/bearer 三类计数均为 0 |

失败矩阵覆盖 executable/version、credential/preflight、protocol/invalid JSON、unknown request、dynamic tool repair/fatal/timeout、awaiting user、conflict/policy、stale revision/generation、lease loss、interrupt、child crash、event backpressure、duplicate replay、unsafe/missing final、DB idempotency冲突、shutdown 和 Windows临时目录清理。

## Vertical slice 与回滚

fake/integration vertical slice 已证明：server-side exact readiness -> 新 plan-drafting run 冻结 Codex -> dedicated worker/runtime router -> typed tools -> safe final projector；existing/general/track 路径不依赖 Codex health。feature-off 测试证明新 plan-drafting 回到 Harness，而已有 Codex conversation/Retry 继续保留 `codex_sidecar_v1`，没有跨 Runtime fallback。

active run 的新 revision 通过控制循环调用 `turn/steer`；cancel/supersede/lease loss 调用 `turn/interrupt`。已有 binding 的 recovered dispatch 不启动第二个 external turn，而将当前 run 安全收敛为 unavailable，后续 learner Retry 创建 fresh same-Runtime run。

## 真实 provider evidence

Child 1 在用户明确批准后执行过一次真实调用：

- endpoint：`https://api.deepseek.com/responses`；
- 1 个 ephemeral thread、1 个 turn；
- dynamic tool attempts 精确 `1 -> 2`；
- `repairable_invalid -> completed`；
- elapsed `7405 ms`；
- request/stream retries 均为 0；
- raw prompt/response 均未保留；
- fallback 未发生；隔离目录最终清理通过。

本 QA 复用该获批证据，没有进行第二次付费调用。该 smoke 只证明当前固定 binary/provider/protocol 的 bounded behavior，不证明长对话质量、真实用户教学效果、quota、SLA 或生产 readiness。

## Release non-claims

- 本记录不批准 push、deploy、生产流量、生产数据迁移或安装包发布。
- 默认开启只表示本地配置默认值；生产 cohort、operator rollout 和真实用户切换仍需独立任务与批准。
- Codex 不是 Aearn 数据/API/确认 authority；Aearn PostgreSQL、public DTO、LearningPlan confirm 和 LearningTrack transaction 仍是唯一 authority。
- 关闭 admission 或代码 rollback 不删除历史 evidence，也不恢复任何已明确删除的旧学习数据。
