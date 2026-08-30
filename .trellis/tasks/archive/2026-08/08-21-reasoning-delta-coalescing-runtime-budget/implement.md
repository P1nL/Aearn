# 实施计划

## 1. 基线与回归 fixture

1. 为 fake App Server 增加 5,000 单字符 delta、稀疏 delta、跨 item/phase、tool repair 和 terminal pending 场景。
2. 先写失败测试证明当前 `runtime_event_budget_exhausted` 和同步投影次数。

## 2. Coalescer

1. 新建 typed coalescer、key、pending group、flush reason 和 timer/size配置。
2. 接入 `CodexAppServerRuntime.run_turn`，确保每次 turn/new subscription 独立，无 backlog 跨 turn。
3. 保留 async subscriber backpressure 和 best-effort terminal 规则。

## 3. Sequence、schema 与 projector

1. 扩展 `RuntimeEvent` source/projection metadata。
2. Additive 修改 receipt schema、constraints、bootstrap、cutover/export/reset/delete inventory。
3. Projector 只消费 coalesced append；completed、commentary correction、terminal discard 保持幂等。
4. 增加 replay/conflict/stale generation/source range tests。

## 4. 预算与可观测性

1. 移除 `len(collected) >= 2_000` 正常失败条件。
2. 增加 raw runaway、pending bytes、item、tool、text、time 的独立限制和 safe codes。
3. 记录无文本 coalescing metrics；验证 Celery heartbeat/projection duration。

## 5. Desktop/API 回归

1. 确认 public stream schema 不需要破坏性版本升级；如新增字段必须 closed parser 同步。
2. 覆盖 slow stream、gap/snapshot、completed calibration、commentary、interrupt、restart、历史折叠。

## 6. 跨 Child browser 验收

- Python 明确语言自动确认，完整计划生成。
- 前端方向 shortlist 后选择课程，完整计划生成。
- 多语言 shortlist。
- draft repair 产生超过 2,000 raw delta 后正常完成。
- refresh/restart/history、console error=0。
- 真实 provider 仅在用户再次明确批准后调用。

## 验证命令

```powershell
uv --directory .\aearn\services\api run python -m pytest `
  tests/test_codex_runtime_adapter.py `
  tests/test_codex_runtime_projection.py `
  tests/test_codex_plan_drafting_cutover.py `
  tests/test_tutor_conversation_runtime.py `
  tests/test_db_bootstrap.py

uv --directory .\aearn\services\api run python -m ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api run python -m pytest
pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
git diff --check
```

## 完成门

- source delta 超过 2,000 的正常 turn 不失败。
- P0/P1 自动测试或 browser evidence 完整。
- 保护两个 Obsidian 用户修改；不 push、不部署。
- 检查通过后按 Phase 3.4 提交并归档 child。
