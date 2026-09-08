# 验证记录（2026-09-08）

## 工作区与隔离

- 基线分支 main，实施分支 codex/09-04-python-document-repair。
- 基线并行改动：两份 .trellis/tasks/.obsidian 插件配置与未跟踪 Python/，保留。
- PowerShell Core 7.6.5；受管 dev 脚本以 pwsh 直接调用 -Status，绕过 package.json 的历史 powershell 启动器。
- 初始 PostgreSQL/Redis 正常，API/Desktop 未运行，API/worker/beat/Desktop 记录 PID 均已失效。
- 为本任务新建独立数据库 aearn_lesson_repair_test_20260908；不修改现有课程数据库。后端检查仅串行使用独立库。

## Desktop

- 实施验证：5 files / 41 tests passed，含 LessonDocumentApi、LessonDocumentPage、LessonDocumentView、TrackLearningWorkspace、LessonDocumentReferenceApi。
- 独立审查：pnpm exec tsc --noEmit 通过；4 files / 37 tests passed，无阻塞发现。
- 无 desktop:check / 全量 build，无真实 provider。

## 浏览器

- Playwright CLI + Edge，127.0.0.1:1420；实际 LessonDocumentPage、API wrapper 与严格 parser，使用合成 11-block Python fixture。
- failed 显示 LESSON_DOCUMENT_INVALID 和安全信息；显式点击重试后 preparing；轮询后 ready，11 个正文块与来源可见。
- 外部网络请求阻断，API fetch 返回 fake 响应；未创建课程、未请求真实模型。
- 最终独立验证轮次：无 pageerror、console warning/error 或 Vite overlay。测试浏览器需 local-network-access 权限供 Vite HMR 使用；修正浏览器权限后通过。
- 截图与可重跑浏览器脚本保存在本机 Codex visualization 的 lesson-repair 目录，未进入 Git。
- 验证用 Vite 和浏览器已关闭，恢复初始未运行状态。

## 后端与最终审查

后端实施首轮完成：

- 独立数据库中串行执行 test_lesson_authoring_feedback.py、test_lesson_document_authoring.py、test_lesson_documents.py、test_db_bootstrap.py：38 passed in 19.04s。
- 受影响 Python 文件与测试 Ruff 通过。
- uv --directory aearn/services/api run python -m mypy app --no-incremental：249 source files，无错误。
- uv lock --check 与后端 git diff --check 通过。
- 最终独立审查通过，无阻塞项；新增 cancelled prepare replay、expired lease reclaim budget、超过 12 项 issue 的 fatal 保留测试，以及 Desktop missing prepare replay 测试。
- 最终后端 41 passed；最终 Desktop 4 files / 38 passed；先前额外 reference API 4 tests passed，生产代码在其后未变化。
- 最终 Ruff、Mypy app（249 source files）、Desktop tsc --noEmit、lock check 与 task-owned diff check 全通过。
- Checker 使用独立 lesson_review_* 数据库并在 finally 删除；初轮 aearn_lesson_repair_test_20260908 也已确认无连接后删除。
- 用户已确认提交归档；实现提交 ed2b1d6。共享工作区在确认间隔切换为 codex/semantic-planning-language-resolution，提交落在该实际分支，任务 branch 元数据同步；保留其他任务提交历史。
