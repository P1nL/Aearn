# Aearn 第一版 release 收口 Implementation Plan

## Checklist

- [x] 复核第一版发布边界与现有实现：实施计划、验收计划、M1-M6 归档任务、当前代码状态。
- [x] 运行第一版 release 相关自动化验证，至少覆盖 onboarding、学习闭环、复习闭环、笔记、恢复学习、设置页和基础构建检查。
- [x] 根据验证结果做问题分级：`P0` / `P1` / `P2`。
- [x] 若存在 `P0/P1` 问题，做最小必要修复并重跑受影响验证。
- [x] 补最小桌面端 smoke，确认自动化之外的关键入口与边界没有回归。
- [x] 形成最终 release 结论与已知问题记录。
- [x] 若实现与文档存在未解释偏差，回写相关 source-of-truth 文档。
- [x] 跑任务验证与 diff sanity check，确认可以进入执行/收尾。

## Validation Commands

- `uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_notes_m5.py`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_dashboard_resume_m6.py`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_worker_import.py`
- `pnpm --dir .\aearn desktop:check`
- `python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-18-05-18-release-readiness`
- `git diff --check`

## Validation Notes

- 这些会触发 `bootstrap_database()` 的后端 pytest 批次按顺序执行，不并行跑。
- 如果自动化检查不能完整覆盖桌面交互边界，需要补本地 smoke。
- 如果发现问题，先重跑最小相关验证，不要每次都全量回归。

## Execution Notes

- 已顺序通过以下后端 pytest：
  - `tests/test_onboarding_m2.py`
  - `tests/test_learning_sessions_m3.py`
  - `tests/test_reviews_m4.py`
  - `tests/test_notes_m5.py`
  - `tests/test_dashboard_resume_m6.py`
  - `tests/test_worker_import.py`
- `pnpm --dir .\aearn desktop:check` 已通过。
- 本地 smoke 已验证：
  - 无 bootstrap context 时进入 onboarding；
  - 建档、生成草稿、确认计划后写入 `localStorage["aearn.bootstrap"]`；
  - reload 后真实请求 `GET /api/users/{user_id}`、`GET /api/plans/{plan_id}`、`GET /api/dashboard`、`GET /api/learning-sessions/resume` 并恢复到学习态；
  - 设置页存在七个分类，且当前页面文案未暴露 `FSRS`、`Attempt`、评分规则或 `due_at` 直接控制项。
- 本轮未发现需要代码修复的 `P0/P1` 阻塞项。

## Risky Areas

- `aearn/services/api/tests/`：发布门禁的核心证据来源。
- `aearn/apps/desktop/`：resume / settings / onboarding 入口最容易在 smoke 阶段暴露边界问题。
- `docs/qa/acceptance-test-plan.md` 与 `docs/plans/learning-agent-implementation-plan.md`：任何 release 结论都必须能回指到这两份文档。

## Review Gates Before `task.py start`

- `prd.md`、`design.md`、`implement.md` 已完整填写。
- 默认策略明确：先验证，再修 `P0/P1`，最后给出发布结论。
- 不新增第一版范围外功能。
- 需要用户确认是否按这套 release 收口计划进入执行阶段。
