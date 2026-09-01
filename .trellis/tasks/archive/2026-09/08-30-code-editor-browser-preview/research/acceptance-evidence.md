# Child04 验收证据（2026-09-02）

## Acceptance mapping

| Acceptance | Evidence |
| --- | --- |
| HTML/CSS/JS Starter 实时预览并可交互 | `CodeEditorArtifact` + 400ms source debounce + native `BrowserPreviewSurface`; learner iframe interaction event bridge |
| 恶意脚本不能影响主应用 | Rust custom protocol/sandbox/CSP/navigation/new-window/download/capability tests；watchdog只 recreate child |
| nonce、Artifact/Session/version mismatch 被拒绝 | Rust bridge tests + TypeScript exact event parser/hook mismatch test |
| resize 保留 model/cursor/scroll/preview | Monaco process-local draft/view state + native bounds observer tests；fixed container layout |
| explicit Run exact latest draft、stale 正确 | `CodeEditorArtifact.test.tsx` |
| cargo/Desktop gates | 最终命令结果追加在下方 |

## Command results

- `pnpm test`（`aearn/apps/desktop`）：**17 files / 126 tests passed**。
- `pnpm --dir .\aearn desktop:check`：**Pass；Vite 131 modules transformed**。
- `cargo fmt --check`、`cargo check`、`cargo clippy --all-targets --all-features -- -D warnings`：**Pass**。
- `cargo test`：**9 passed**，覆盖 exact main capability + app-command ACL、CustomProtocol、script-only sandbox/CSP、default-port-only navigation、popup/download deny、source hash/bounds、nonce/scope/version/generation/replay/extra/oversize、generation-specific data directory 与 learner-frame heartbeat。
- `python ./.trellis/scripts/task.py validate 08-30-code-editor-browser-preview`：**Pass；implement 6 / check 2**。
- `git diff --check`：**Pass**，仅输出当前 checkout 已知 line-ending warning。
- 真实 native WebView2 smoke：**Pass**。临时 env-gated fixture 通过 `pnpm desktop:dev` + CDP main target执行并已删除；safe source进入 ready并产生 console/interaction，恶意 source的 fetch/WebSocket、parent、top navigation、popup、form、download和 app/core invoke均未取得 authority；wrong nonce/version/hash fail closed；hang只 bounded recreate一次后显示 `PREVIEW_HOST_UNRESPONSIVE`，main draft/focus保持，切回安全 source恢复 ready。child未暴露为 CDP target，已明确记录而未用 Vite web fallback冒充。

## Non-claims

未调用真实 provider/executor；未运行 Docker conformance、生产镜像、签名、发布、push、deploy 或生产迁移。本证据不构成生产隔离或 release approval。
