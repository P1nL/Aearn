# Aearn 第一版 release 收口报告

日期：2026-05-18  
任务：`05-18-05-18-release-readiness`

## 范围

本报告只覆盖第一版既有范围内的发布收口，不扩展到第二版功能。判定基线来自：

- `docs/plans/learning-agent-implementation-plan.md`
- `docs/qa/acceptance-test-plan.md`

## 自动化验证

### 后端 pytest

- `uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py`
  - 结果：`7 passed`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py`
  - 结果：`13 passed`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py`
  - 结果：`4 passed`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_notes_m5.py`
  - 结果：`3 passed`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_dashboard_resume_m6.py`
  - 结果：`5 passed`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_worker_import.py`
  - 结果：`1 passed`

### 桌面端构建

- `pnpm --dir .\aearn desktop:check`
  - 结果：`tsc && vite build` 通过

## 手工 smoke

### 首次进入

- 在没有 `localStorage["aearn.bootstrap"]` 的情况下整页 reload。
- 页面进入 onboarding，而不是直接进入学习/复习/笔记页。
- `aearn-api` 健康状态正常，课程目录可加载。

### 建档与确认计划

- 通过 onboarding 完成用户建档。
- 生成计划草稿并确认。
- 确认后成功写入：
  - `localStorage["aearn.bootstrap"].userId`
  - `localStorage["aearn.bootstrap"].planId`

### returning-user / resume

- 写入 bootstrap 后整页 reload。
- 前端真实请求链包含：
  - `GET /api/users/{user_id}`
  - `GET /api/plans/{plan_id}`
  - `GET /api/dashboard`
  - `GET /api/learning-sessions/resume`
  - `POST /api/learning-sessions/start`
- 页面恢复到学习态，并显示恢复/复习提示，不会错误退回 onboarding。

### 设置页边界

- 设置页存在七个分类：
  - 外观
  - 模型设置
  - 学习偏好
  - 复习
  - 通知设置
  - 记录与隐私
  - 关于与诊断
- 当前设置页文案和可见控件未暴露 `Attempt`、`FSRS`、评分规则、`due_at` 等越权控制项。

## 问题分级

### P0

- 未发现阻塞发布的 `P0` 问题。

### P1

- 本轮未发现必须修复或必须纳入已知问题清单的 `P1` 问题。

### P2

- 后端测试中存在 FastAPI `HTTP_422_UNPROCESSABLE_ENTITY` 的 deprecation warning。
- 该项目前不影响第一版用户主闭环和发布判断，记录为后续维护项，不阻塞发布。

## 文档偏差检查

- 本轮未发现必须立即回写到 `docs/` 才能维持 contract 一致性的实现偏差。
- 因此本次收口不修改 `docs/` source-of-truth 文档，只在任务内记录发布证据和结论。

## 发布结论

结论：`ready to release`

理由：

- 第一版主闭环对应的后端验证和桌面端构建检查均已通过。
- onboarding、学习闭环、复习/恢复入口、笔记相关路径、设置页边界已覆盖到本轮自动化验证或手工 smoke。
- 未发现阻塞发布的 `P0` 问题，也未发现需要强制列入已知问题清单的 `P1` 问题。
