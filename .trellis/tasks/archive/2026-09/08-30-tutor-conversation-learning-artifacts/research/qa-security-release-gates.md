# QA、安全与发布门摘要

## P0 原则

- 破坏 server authority、user scope、persistence、hidden/private boundary、public API/SSE、safe execution 或 cutover inventory 的问题阻止归档。
- PostgreSQL/bootstrap-heavy tests 单进程串行；静态搜索或 build 不能替代真实 fixture/browser 交互证据。
- 测试、ledger 和日志不得记录 raw learner message/code、prompt、provider body/reasoning、hidden tests、rubric、command/path/container/secret。

## 必测坏路径

- 跨用户/track/conversation/session/artifact 访问。
- stale version、重复 idempotency、同 key 不同 body、duplicate event、out-of-order/gap/cursor invalid/reconnect。
- provider unavailable、executor unavailable、feature off、Preview off、unknown contract/extra field。
- hidden test/answer/SQL hidden dataset/rubric/source private excerpt 泄漏。
- Artifact 与 Gate/Review 双写 mastery/progress。
- Preview：无限循环、导航、network、popup、download、form、parent access、Tauri IPC、invalid nonce、oversized log、crash/recreate。
- Markdown：raw HTML/script/style、危险 URL、非法 color/size、低对比或不可见内容。
- Item Bank：答案不唯一、standard answer失败、starter已通过、Hint泄漏、rubric错配、reviewer非独立、content hash变化后复用旧审核。

## Desktop

- 1440x900、900x900、390x844；Artifact/branch/drawer无overflow。
- keyboard、focus return、screen reader label、Escape、reduced motion、scroll anchor。
- console error/warning为零；活动工件更新不得抢焦点或滚动。

## 默认命令边界

- API：focused pytest -> full serial pytest -> Ruff -> Mypy -> lock。
- Executor：pytest/Ruff/Mypy；真实Docker conformance需另行批准。
- Desktop：desktop:test、desktop:check；Tauri Preview child额外cargo check和安全smoke。
- Database：bootstrap twice、cutover exhaustive inventory、export/reset/delete。
- Trellis：task.py validate、git diff --check。

## 非声明

- fake provider不证明真实模型教学质量、延迟或quota。
- local runner/Preview不证明生产container隔离；空image-lock不能声称container_verified。
- planning/test通过不是push、deploy、生产迁移或release approval。
