# 当前证据

## 语言选择

- `app/db/schema.sql` 中 `language_courses` 没有结构化 planning intent metadata。
- `planning_questions.py` 对 `language_id` 直接查询全部未归档课程并默认推荐首项。
- `language_capabilities.py` 已有 canonical language、aliases 与 public course language map，可复用做明确语言归一化。
- 用户实测“我想学前端”仍展示全部八门课程；明确语言也会被再次询问。

## Runtime 中断

- 最新失败 safe code：`runtime_event_budget_exhausted`。
- 失败轮次包含 1,989 个 reasoning delta：38 + 1,852 + 99；`aearn_learning_plan_draft` 在 sequence 1,899/1,900 完成，第三段 reasoning 在 2,000 被中断。
- session 七项 facts 均 confirmed，但 draft count 为 0。
- terminal cleanup 正常：未完成 reasoning 被清空并标记 discarded，无永久 streaming row。
- `codex_adapter.py` 当前使用 `len(collected) >= 2_000` 作为 fatal 条件；这把 provider 分片粒度错误变成业务失败。

## 参考方向

- Codex 使用 item lifecycle 和 item/index 归属来管理 reasoning delta；UI 通常累积同 item 文本，completion 再提交历史单元。
- Aearn 应使用 coalesced projection、completed calibration 和 snapshot recovery；不通过简单提高硬编码阈值掩盖问题。
