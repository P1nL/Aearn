# Codex Sidecar 协议验证结果

## 当前结论

- 日期：2026-08-18。
- 离线协议结论：通过。
- 本机 Codex App Server preflight：通过。
- 真实 `deepseek-v4-flash` Responses smoke：通过。
- 最终 DeepSeek-specific Go/No-Go：`Go`。
- Child 2 前置技术条件：已满足；本会话未启动 Child 2。
- 工作提交：`5804d628 feat(runtime): add Codex sidecar adapter and supervisor`。
- Child 1 已满足归档条件。

## 实施范围

新增独立 spike 包 `aearn/services/api/app/agents/codex_spike/`，未接入正式 Tutor/API/DB/LearningPlan/Desktop 组合根。实现包括：

- Windows async stdio JSON-RPC request/response、notification、server request、timeout、stderr 分离和 process-tree 终止；
- 未知 notification 计数忽略、未知 server request fail closed；
- typed dynamic tool 的 `repairable_invalid -> completed`、fatal 与 timeout 场景；
- fake app-server；
- fake DeepSeek Responses repair、fatal、provider timeout、stream interrupted 和 invalid event fixture；
- 隔离 Codex Home/custom provider config；
- 本机 binary/version/schema/initialize/thread custom-provider preflight；
- interrupt、child crash、invalid JSON、request timeout 与 redaction；
- 显式批准后才能运行的真实 smoke 入口，默认不保留隔离 Home、raw prompt 或 raw response。

## 本机 App Server 证据

| 项目 | 结果 |
| --- | --- |
| binary | `E:\Codex-win-x64-26.616.81150\resources\codex.exe` |
| version | `codex-cli 0.142.0-cometix` |
| platform | `windows` |
| transport | `stdio` JSONL |
| strict config | 通过 |
| initialize 返回 Codex Home | 与临时隔离 Home 精确一致 |
| model | `deepseek-v4-flash` |
| model provider | `aearn_deepseek` |
| wire API | `responses` |
| OpenAI auth | `requires_openai_auth = false` |
| credential source | 仅 `DEEPSEEK_API_KEY` 环境变量 |
| thread/start model match | 通过 |
| thread/start provider match | 通过 |
| dynamic tools schema | 通过 |
| final config fingerprint | `da15fce934fea1d19c89d4c5645e4dfc64721a0ca8c56c0cfb90109c5a3f5ca7` |

从本机 `generate-json-schema --experimental` 读取并确认的必需表面：

- client request：`initialize`、`thread/start`、`turn/start`、`turn/interrupt`；
- server request：`item/tool/call`；
- notification：`thread/started`、`turn/started`、`item/started`、`item/completed`、`turn/completed`。

Preflight 使用临时目录并在验证后删除；没有把用户全局 `C:\Users\PINKING\.codex` 作为 `CODEX_HOME`，也没有读取或复制全局 auth/session/memory/plugin 状态。

## 真实 DeepSeek Smoke 结果

用户于 2026-08-18 明确批准一次真实调用。实际执行结果：

| 项目 | 结果 |
| --- | --- |
| status | `completed` |
| model | `deepseek-v4-flash` |
| provider | `aearn_deepseek` |
| endpoint | `https://api.deepseek.com/responses` |
| thread/turn | 1 个 ephemeral thread、1 个 turn |
| dynamic tool attempts | 精确 `1 -> 2` |
| 第一次结果 | `repairable_invalid` |
| 第二次结果 | `completed` |
| turn terminal | `completed` |
| request retries | `0` |
| stream retries | `0` |
| elapsed | `7405 ms` |
| input SHA-256 | `4438b343733c2bbf752457b94a4bce88d9b5209c0a06e950b068885e7f7cfaa1` |
| opaque turn SHA-256 | `0bd3f3b17b2cac7ee129b850a0a0a4cfc67ab3edaac9b1ea8432f3787c5e51c8` |
| retained raw prompt | `false` |
| retained raw response | `false` |
| model/provider/protocol fallback | 未发生 |

本 smoke 没有使用 OpenAI、其他 DeepSeek 模型或 Chat Completions。输入只包含合成指令和 `{attempt, value="bounded"}`，不含用户、数据库、Tutor 或 LearningPlan 数据。

### Windows 清理修复记录

首次真实调用的模型/tool rubric 已完成，但返回后检查发现临时隔离根目录因 Windows asyncio subprocess transport handle 尚未释放而未立即删除；没有遗留 app-server 进程，也没有写入全局 Codex Home。

已在最终结论前完成以下修复与验证：

1. stdio client 在 stdout/stderr/waiter 完成后显式关闭 subprocess transport；
2. 隔离根目录删除增加 bounded retry，删除失败会把 smoke 判为失败；
3. 精确删除首次 smoke 与早期 evidence 遗留的两个临时目录；
4. 使用真实本机 App Server、但不调用 provider，重新执行 preflight + cleanup；结果为 `preflight_ready=true`、`root_exists_after_cleanup=false`；
5. 增加隔离目录清理回归测试。

因此最终 Go 是基于“真实模型/tool repair 已通过 + 修复后的真实 App Server 关闭/清理已通过”的组合证据，不把首次清理缺陷隐藏或忽略。

## 离线自动化矩阵

| 场景 | 结果 |
| --- | --- |
| request/response correlation | 通过 |
| notification/event lifecycle | 通过 |
| typed dynamic tool input | 通过 |
| 第一次 `repairable_invalid`、第二次 completed | 通过 |
| fatal tool result -> failed turn | 通过 |
| server request timeout | 通过，fail closed |
| request timeout | 通过，可终止 child |
| `turn/interrupt` -> interrupted | 通过 |
| child 启动即 crash | 通过，可区分 |
| child turn 中 crash | 通过，可区分 |
| invalid JSON | 通过，协议失败 |
| unknown server request | 通过，`-32601` 后 fail closed |
| unknown notification | 通过，忽略并计数 |
| stderr secret/path/raw prompt marker | 通过，已脱敏 |
| fake Responses provider timeout | 通过，可区分 |
| fake Responses stream interrupted | 通过，可区分 |
| fake Responses invalid event | 通过，fail closed |
| 隔离根目录清理 | 通过 |
| 模型/provider/protocol fallback | 未实现且测试固定精确目标 |

## 最终验证结果

- focused pytest：`17 passed, 1 skipped`。
  - skipped 项是默认关闭的真实 provider pytest 入口；本次已通过受控脚本执行一次获批 smoke，为避免产生第二次付费调用，没有再次用 pytest 调用 provider。
- Ruff：通过。
- Mypy：通过，6 个 spike source files 无问题。
- Trellis validate：通过。
- `git diff --check`：通过；仅报告既有 `.trellis/tasks/.obsidian/workspace.json` 行尾提示，未覆盖或回滚该文件。
- 进程检查：无遗留 fake app-server 或 Codex app-server 进程。
- 临时目录检查：首次 smoke 与早期 evidence 临时目录已删除；修复后的 cleanup proof 返回 `false`。

## 最终 Go 条件

以下条件均已有证据：

1. Windows stdio child 可稳定 initialize/thread/turn 并可靠终止；
2. 隔离 custom provider 精确选择 `deepseek-v4-flash` + Responses；
3. 真实 DeepSeek Responses stream 可被当前 Codex build 完整消费；
4. typed dynamic tool 收到结构化输入；
5. 真实模型在同一 Turn 内完成 `repairable_invalid -> retry -> completed`；
6. interrupt、timeout、provider stream failure、invalid protocol 和 child crash 可区分；
7. credential、raw prompt、raw response、reasoning 与 provider body 未写入结果证据；
8. 不使用全局 Codex Home；隔离状态可删除；
9. 未发生模型、provider 或协议 fallback。

结论：Child 1 可判定为 `Go`，后续 Child 2 的技术前置条件已满足，但 Child 2 仍需独立启动，不在本任务中自动开始。
