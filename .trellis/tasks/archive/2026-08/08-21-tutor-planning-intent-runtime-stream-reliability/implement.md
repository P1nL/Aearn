# 实施计划

## 阶段 1：Child 1——课程意图与动态 Generated UI

1. 增加 taxonomy/关联 schema、trigger/index、bootstrap backfill 和 coverage 查询。
2. 扩展语言别名和闭合 intent resolver，不读取 Tutor/model/reasoning 文本。
3. 在 plan_drafting input acceptance 中写唯一明确语言的 `deterministic_input` fact。
4. 为方向/多语言/conflict 生成 candidate course IDs，并持久化 exact typed request presentation。
5. Desktop 取消语言问题默认选中，未选择时禁用提交。
6. 增加 unit/PostgreSQL/API/Desktop/browser tests 和 source-of-truth docs。
7. 运行 Child 1 focused/full gates，提交并归档 Child 1。

## 阶段 2：Child 2——Reasoning delta 合并与 Runtime 预算

1. 增加 item/index/phase-aware `RuntimeDeltaCoalescer` 与 timer/size/boundary flush。
2. 将 raw source sequence 与 projection sequence 分离；receipt 保存安全 range/count/hash。
3. 删除正常 turn 的 2,000 source-event 失败条件，增加 raw runaway、字符、item、tool、time、pending bytes 预算。
4. 让 PostgreSQL/SSE 只消费 coalesced chunks，completed item 做最终校准。
5. 覆盖 slow consumer、burst、tool repair、commentary、interrupt、restart、gap/replay。
6. 使用 Child 1 场景完成完整 plan drafting browser flow；真实 provider 仅在用户再次明确批准后调用。
7. 运行 full gates，提交并归档 Child 2。

## 最终集成门

```powershell
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run python -m ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate 08-21-tutor-planning-intent-runtime-stream-reliability
git diff --check
```

Browser 至少覆盖 1440×900、900×900、390×844，以及 Python 自动确认、前端 shortlist、多语言 shortlist、conflict、长 reasoning tool repair、refresh/restart、console error=0。

## 完成门

- 两个 child 均按顺序归档并有独立 work commit/quality evidence。
- Parent acceptance matrix 全部通过。
- 受保护的 `.trellis/tasks/.obsidian/plugins/translate/data.json` 与 `.trellis/tasks/.obsidian/workspace.json` 不进入提交。
- 不 push、不部署；真实 provider 调用遵循显式批准门。
