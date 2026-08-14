# 实施计划

## 前置检查

- [ ] 加载 `trellis-before-dev`，读取 backend/database/cross-layer specs、父任务和本 child 工件。
- [ ] 核对 Pending Input child 的状态集合与 request fields，确保 Queue 不绕过 waiting contract。
- [ ] 复核现有 conversation/run lock order、idempotency、dispatch 和 reset/export/cutover 代码。

## Database/repository

- [ ] 新增 Queue schema、constraints、indexes 和 bootstrap-twice regression。
- [ ] 实现 enqueue/list/edit/delete/claim/steer repository transactions。
- [ ] 添加 export/reset/cutover classification。

## Service/API/SSE

- [ ] 增加 delivery mode 与 additive placement response。
- [ ] 实现 Queue list/mutation/steer routes 和 stable errors。
- [ ] 实现 completed drain、failure/stop pause、next-send wake coordinator。
- [ ] 实现 run cancel route/service，复用 cancellation persistence。
- [ ] 增加 Queue projection/event/replay 和 Desktop TS parser seam。

## Tests/docs

- [ ] pure + PostgreSQL + API + SSE 测试覆盖 FIFO/并发/边界/Steer/drain/pause/wake/cancel/fence/legacy。
- [ ] 更新 API、DB、runtime、user flow 和 acceptance docs。

## 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_repository.py tests/test_tutor_routes.py tests/test_tutor_sse.py tests/test_tutor_run_loop.py tests/test_tutor_conversation_history.py tests/test_tutor_latest_input_smoke.py tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-13-tutor-persistent-queue-stop
git diff --check
```

## Review gate

- [ ] no-active/active/paused 三条提交路径都原子且可重放。
- [ ] completed 是唯一自动 drain 终态。
- [ ] stop 不删除 Queue，不取消 planning session，不承诺 provider 硬 abort。
- [ ] 旧客户端兼容未回退。
- [ ] 不实现最终 UI 组件。
