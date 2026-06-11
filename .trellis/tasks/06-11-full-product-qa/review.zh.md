# 完整产品 QA Review

## 你需要审核的结论

这个任务不是新增功能，而是对当前 Aearn 本地产品基线做一次完整 QA。目标是确认 onboarding、学习、复习、笔记、设置、恢复入口和关键后端写库时机仍然一致；发现的问题按 P0/P1/P2 分级，P0 必须修，P1 要么修复要么拆成明确 follow-up。

## 本轮 QA 范围

1. 文档一致性：先对齐 `docs/README.md`、`docs/product/user-flows.md`、`docs/product/frontend-interaction-spec.md`、`docs/architecture/api-contract.md`、`docs/architecture/database-schema.md`、`docs/architecture/fsrs-scheduling-spec.md`、`docs/qa/acceptance-test-plan.md`。
2. 后端确定性验证：顺序跑 onboarding、learning、review、notes、dashboard/resume、LLM mock/failure、runner/runtime、local data boundary 等 pytest 批次。
3. 桌面端验证：跑 `pnpm --dir .\aearn desktop:check`，并记录 Vite chunk-size warning 是否只是已知非阻塞警告。
4. 本地浏览器 smoke：用 `pnpm --dir .\aearn dev:test-data` 准备数据，检查 `http://127.0.0.1:8001/health` 和 `http://127.0.0.1:1420`。
5. 用户流程 smoke：覆盖冷启动/onboarding、dashboard/resume、学习概念判断和练习、复习自然热身和一题一卡、笔记抽屉/笔记页、设置七分类。
6. 真实模型 QA：直接使用本地已配置 provider 跑模型支持的 onboarding/learning/review 路径，检查模型输出、不可用/非法输出处理和安全边界。
7. 数据安全检查：确认 warmup 不创建 `Attempt`、不写 `review_logs`、不更新长期 `ReviewState`；正式复习提交才更新 FSRS。

## 不做

- 不做大规模产品重设计。
- 不新增当前 source-of-truth 之外的新能力。
- 不碰生产数据或生产部署。
- 不输出、记录或提交 `.env` secrets、API key、raw prompt、hidden tests、provider reasoning 或 raw provider error body。

## 计划执行顺序

1. 执行 `python .\.trellis\scripts\task.py start 06-11-full-product-qa`。
2. 创建 `qa-report.md`，记录文档、命令、浏览器 smoke、真实模型 QA、发现、修复和最终 verdict。
3. 顺序跑后端测试，避免 bootstrap DB deadlock。
4. 跑 desktop build/type gate。
5. 启动本地测试数据环境并做浏览器 smoke。
6. 直接用模型跑可配置路径，但证据只记录产品/API 层结论，不记录 secrets 或 provider 原始内容。
7. 对 P0/P1 做局部修复或拆 follow-up。
8. 最终跑 `git diff --check` 和 Trellis validate，再按提交、归档、journal、push 收尾。

## 已确认决策

本轮完整 QA 直接包含 live-model provider 检查。如果本机缺少必要模型配置或 provider 不可用，`qa-report.md` 必须把它记录为明确 blocker/finding，而不是静默降级成 mock-only。
