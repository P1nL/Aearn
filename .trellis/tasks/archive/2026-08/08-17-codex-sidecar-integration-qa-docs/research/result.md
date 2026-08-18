# Codex Sidecar 集成 QA 结果

## 当前结论

- 日期：2026-08-18。
- Child 1-5：均已完成并归档。
- 非真实 provider 全链路验收：通过。
- 真实 provider：复用 Child 1 已明确批准并完成的一次 `deepseek-v4-flash` Responses tool-repair smoke；本 QA 未发起第二次付费调用。
- 集成结论：本地 Go；不是 production/release approval。
- 用户全局 `C:\Users\PINKING\.codex`：未读取、未修改。
- push、deploy、Codex 安装/升级、生产流量：未执行。

## Child 证据汇总

| Child | 主要结果 |
| --- | --- |
| Protocol spike | Windows stdio/strict config、exact provider、dynamic tool repair、interrupt/crash/redaction；获批真实 smoke `repairable_invalid -> completed` |
| Runtime adapter/supervisor | Aearn-owned contracts、single owner、generation、isolated Home、dedicated worker、shutdown/backpressure |
| LearningPlan tools | typed context/draft、repair/awaiting/conflict/policy/fatal/timeout、facts/lease/generation fence、duplicate replay |
| Durable projection | immutable Runtime kind、private binding、append-only receipt/public error、safe final、SSE/history redaction |
| Plan-drafting cutover | exact readiness、default-enabled admission、Runtime-filtered workers/router、steer/interrupt、same-Runtime Retry、rollback |

## 失败矩阵

| 触发 | 稳定结果 |
| --- | --- |
| executable missing / unsupported version | `codex_missing` / `unsupported_codex_version`，不准入 |
| credential missing / initialize-account preflight失败 | `provider_credential_missing` / `runtime_preflight_failed` |
| isolated Home mismatch / ownership冲突 | `isolated_home_mismatch` / `ownership_conflict` |
| invalid JSON / unknown server request / child crash | 当前 generation fail closed；pending work收到稳定 connection/protocol failure |
| request/server request/provider timeout | timeout code；child可终止；无无限等待 |
| event queue满 | `runtime_event_backpressure_exhausted` |
| typed tool schema/domain invalid | `repairable_invalid`，最多 2 次 repair |
| facts缺失 | `awaiting_user`，缺失 stable keys |
| stale revision/lease/generation/facts | `conflict` 或 stale receipt，无越权写入 |
| policy/unavailable/fatal/预算耗尽 | 失败 tool result + bounded terminal code |
| duplicate draft/event | exact replay；不同安全事实 idempotency conflict |
| unsafe/missing final | `TUTOR_RUNTIME_OUTPUT_BLOCKED` / `TUTOR_RUNTIME_OUTPUT_MISSING` |
| feature on但readiness缺失/过期/不匹配 | `503 TUTOR_RUNTIME_UNAVAILABLE`，first-turn无残留 conversation |
| Harness/Codex worker queue错配 | no claim / no action |
| higher input revision | `turn/steer` |
| cancel/supersede/lease loss/control failure | `turn/interrupt` 或 unavailable收敛 |
| recovered job已有binding | 不启动第二 external turn；same run unavailable |
| learner Retry | fresh run继承 `codex_sidecar_v1`，无 Harness fallback |
| shutdown | interrupt active、关闭stdio、释放owner；无残留 sidecar进程 |

## 自动化与安全结果

- Codex focused：`66 passed in 16.91s`，`-m "not real_provider"`。
- Public/SSE/history/redaction：`21 passed in 10.70s`。
- 完整 API：`660 passed, 2 skipped in 145.57s`；skips 为 opt-in real-provider tests。
- Ruff：通过。
- Mypy：`192 source files` 通过。
- compileall、`uv lock --check`、bootstrap twice、cutover inventory、Desktop build：通过。
- sidecar process leak：`0`。
- credential/private-key/bearer literal scan：`0 / 0 / 0`。
- DB/API/SSE/Desktop 继续使用 Aearn DTO；Runtime external IDs、reasoning、raw prompt/tool/provider body不进入公开面。

## 真实 Smoke 证据

Child 1 的获批调用固定：

- model：`deepseek-v4-flash`；
- provider：`aearn_deepseek`；
- endpoint：`https://api.deepseek.com/responses`；
- 1 ephemeral thread、1 turn；
- dynamic tool attempts：`1 -> 2`；
- terminal：`completed`；
- elapsed：`7405 ms`；
- request/stream retry：`0 / 0`；
- raw prompt/response retained：`false / false`；
- fallback：未发生；
- 隔离 Home：最终清理通过。

本 QA 不重复调用。该证据不证明长对话教学质量、quota、SLA 或生产 readiness。

## 回滚演练

1. `TUTOR_CODEX_PLAN_DRAFTING_ENABLED=false` 时新的 plan-drafting 选择 Harness。
2. 已冻结 Codex conversation在 feature off 后仍保持 Codex；active/history evidence不迁移、不删除。
3. general/track/proactive scope不依赖 Codex readiness。
4. active run只完成或interrupt；Retry继承原 Runtime。
5. dedicated worker可停止；Harness worker和既有公开读取继续可用。

## 文档同步

已更新或新增：

- `docs/README.md`；
- `docs/architecture/tutor-harness-runtime.md`；
- `docs/architecture/api-contract.md`；
- `docs/architecture/database-schema.md`；
- `docs/setup/development-environment.md`；
- `docs/setup/codex-sidecar-runtime.md`；
- `docs/product/user-flows.md`；
- `docs/qa/acceptance-test-plan.md`；
- `docs/qa/tutor-harness-release-readiness.md`；
- `docs/qa/codex-sidecar-integration-readiness.md`；
- `.trellis/spec/backend/codex-runtime-sidecar.md`。

## 非声明与残余风险

- 默认开启不是生产 cohort 批准。
- Aearn 不捆绑或自动安装/升级 Codex。
- 仅新 `plan_drafting` 支持 Codex；其他 Tutor scope未切换。
- Codex不是 LearningPlan confirm、LearningTrack、API、DB或public DTO authority。
- dynamic tools仍依赖固定 Codex版本的 experimental surface；升级必须重新preflight和验收。
- 单次真实 smoke不是完整长对话或真实用户教学质量验收。
