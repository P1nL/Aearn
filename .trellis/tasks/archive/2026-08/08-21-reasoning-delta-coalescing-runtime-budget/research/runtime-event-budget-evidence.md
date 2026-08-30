# Runtime 事件预算证据

## 最新失败

- safe code：`runtime_event_budget_exhausted`。
- source reasoning delta：1,989。
- 分段：38（completed）、1,852（completed）、99（terminal 前未完成）。
- tool：`aearn_planning_context_read` 与 `aearn_learning_plan_draft` 均 completed。
- session 七项 planning facts confirmed，draft count=0。
- terminal cleanup 将未完成 reasoning 清空并标记 discarded。

## 根因

`codex_adapter.py` 使用 `len(collected) >= 2_000`，把 provider 的微小分片数量当成 turn 生存预算。第二段 reasoning 约 4,867 字符却产生 1,852 个 delta，证明 count-based hard cap 不能代表文本、时间或资源风险。

## 修复约束

- 不以简单提高阈值作为最终方案。
- Coalescing 必须 item/index/phase aware。
- completed item 继续是终态 authority。
- UI lag 与模型 turn 成功分离。
- receipts/logs 不保存 raw reasoning。
