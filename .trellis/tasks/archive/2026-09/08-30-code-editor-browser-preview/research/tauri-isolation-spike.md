# Tauri 2.11.1 隔离 Preview Spike（2026-09-01）

## 本地源码事实

- `Cargo.lock` 锁定 `tauri 2.11.1`。
- `WebviewBuilder::new` / `Window::add_child` 在 Windows 同步 command 或 event handler 中可能因 WebView2 deadlock；实现使用 async Tauri commands。
- 稳定 `WebviewUrl` 的 app-owned scheme 使用 `CustomProtocol`；实现未使用 data URL，也未把自定义 scheme 当作 `External` HTTP(S)。
- `WebviewBuilder` 提供 `on_navigation`、`on_new_window`、`on_download`、`incognito(true)`、`devtools(false)` 与独立 data directory。
- 本地 capability schema 明确：`windows:["main"]` 会授权 main window 的所有 child webviews，并忽略 `webviews`。因此 default capability 已收紧为 `webviews:["main"]`，Preview label 固定为 `aearn-preview-*` 且不匹配任何 capability。

## 可行实现边界

1. main WebView 通过 async command 创建同一 native window 内的 child webview，以 DOM viewport logical bounds 定位。
2. child webview 只加载 `aearn-preview://localhost/host/{host_id}` app-owned custom protocol；protocol query 绑定 current generation/nonce。
3. trusted host page 只挂一个 `sandbox="allow-scripts"` learner iframe；不授予 same-origin/forms/popups/downloads/top-navigation。
4. response CSP 使用 `default-src/connect-src/object-src/base-uri/form-action 'none'`，只允许 inline script/style 与 data/blob image/media；native top-level navigation/new-window/download handler继续 deny。
5. learner source 作为 escaped JavaScript string进入 trusted host，再写入 sandboxed `srcdoc`；不会成为 trusted host markup，也不会进入 main DOM。
6. learner iframe instrumentation 发出 ready heartbeat、bounded console/runtime/error/interaction message。trusted host 加入 nonce/scope/generation/sequence后用 title-change交给 Rust；Rust exact validate 后才向 main WebView emit typed event。
7. heartbeat 定时器位于 learner iframe event loop。`while(true)` 阻塞 learner document 时不能继续产生 heartbeat；main WebView 2.8s watchdog 调用 async recreate，仅关闭/重建 child preview。

## 明确非声明

- child WebView + iframe/CSP/capability 是 Desktop 本地交互隔离，不是 reviewed container fleet、`container_verified`、生产浏览器沙箱认证或 release approval。
- 未运行真实 provider、真实 executor、Docker conformance、生产 image build/sign/publish、push、deploy 或生产迁移。
