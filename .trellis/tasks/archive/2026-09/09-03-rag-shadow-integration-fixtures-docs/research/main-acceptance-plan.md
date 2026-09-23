# Child06 独立验收编排

- 前置child05：8a6273c实现，5f1b58f归档；用户批准继续；不推送。
- GPT-6-Sol两个实现子代理分别拥有compatibility adapter/tests与scenario/demo/integration tests，主代理拥有文档、规格、真实运行时、提交/归档。实现完成后独立check。
- 基线：全app/tests Ruff通过；全app Mypy 273源文件通过；desktop:check的tsc和Vite构建通过。
- 测试库：aearn_rag260_cli_retrieval_shadow_tests_20260924_ff28fe0a，显式bootstrap，无已发布demo指针。
- 演示库：aearn_rag260_cli_retrieval_shadow_demo_20260924_48bb9999，显式bootstrap，用于CLI真实子进程演示、独立read-only adapter检查。
- 两库均main新建，严禁访问业务库、真实provider、.env或网络抓取；结束零连接DROP，无FORCE。
- fixture-v1已有4 routes/6 ecosystems，禁止为演示更改不可变fixture内容/摘要；新manifest只组织场景。
- AC需要backend/DB/public Lesson-Tutor-citation回归、Desktop typed、无公开route/schedule接线、source-link/hygiene、可重复demo；不能将synthetic/null-shadow解释成public可用。
