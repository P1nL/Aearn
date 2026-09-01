# Code Editor and Isolated Browser Preview 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [x] 先做最小 Tauri isolation spike并记录可行边界
2. [x] 实现 Monaco model/draft/stale/read-only
3. [x] 实现 preview host lifecycle/CSP/capability
4. [x] 实现 nonce bridge、console/error和hang recreate
5. [x] 实现 fixed responsive layout和scroll preservation
6. [x] 接入 explicit Run action
7. [x] 完成恶意 payload、多视口与 disposable native WebView2 smoke（不调用真实 provider/executor）

## Validation

- [x] Vitest editor/preview state tests
- [x] Tauri cargo check
- [x] 恶意 Preview 自动化矩阵
- [x] desktop:test/desktop:check
- [x] 真实 native WebView2 smoke（临时 env-gated fixture 已删除；未用 Vite web fallback 冒充）

## Native Smoke Evidence

- 使用 `VITE_NATIVE_PREVIEW_SMOKE` 临时 fixture 与 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333` 启动真实 `pnpm desktop:dev`；测试后恢复 `main.tsx`、删除 fixture/backup，并确认 1420/9333 端口关闭。
- CDP `/json/list` 始终只暴露 1 个 main target：`page / Aearn / http://127.0.0.1:1420/`；`aearn-preview-*` child 因 dedicated data directory + `devtools(false)` 未暴露为 CDP target，因此 child DOM/network 采用已知恶意 source 的 bounded bridge、native handler、下载文件缺失与 Rust contract gate交叉验证。
- native 断言：交互事件到达；fetch/WebSocket、parent、top navigation、popup被阻断；唯一下载文件未产生；main console 无 error/warning；main command 正常创建/关闭 host，错误 nonce/version/hash分别返回 `PREVIEW_HOST_IDENTITY_REJECTED` / `PREVIEW_HOST_SOURCE_INVALID`。
- `__TAURI_INTERNALS__` 对象在 WebView2 learner subframe 中可观察，但 child 不匹配任何 capability，`AppManifest::commands` 把自定义命令纳入 ACL且只授权 `webviews:["main"]`，每个 command仍二次执行 `require_main_webview`，因此 app/core invoke没有可调用 authority；`connect-src 'none'` 独立负责阻断 network/connect。
- native smoke 发现并修复两项仅真实 WebView2暴露的问题：Windows CustomProtocol 回调使用默认 HTTPS 端口，navigation allowlist现允许协议默认端口但拒绝非默认端口/userinfo/fragment；无限循环后复用同一 WebView2 data directory不能可靠恢复，recreate现按 generation轮换 directory，并把自动重建限制为一次，随后 `PREVIEW_HOST_UNRESPONSIVE` fail closed。最终状态序列为 `ready -> creating -> recreating -> creating -> error`，main draft/focus保持；改回安全 source 后恢复 `ready` 与 `native.recovered`。

## Review Gates

- [x] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [x] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [x] 运行相关最小验证后，再运行所属 package 完整门。
- [x] 本 child 不需要 PostgreSQL bootstrap。
- [x] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Rollback Points

- 独立关闭 Preview feature，保留编辑器但禁止 model 发要求预览的候选
- 绝不在 main DOM 执行任意 source
- 保留 artifact state为安全 unavailable

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。
