# 项目运行资源授权记录（2026-09-27）

用户确认项目开发期间持续联网/真实API，累计300元、240元提醒、保留免费搜索。正式范围和核算规则只维护在 `docs/setup/project-external-resource-policy.md`，机器可读登记在 `docs/qa/project-development-api-budget.json`。

本次仅文档、agent入口、规划与登记更新。无付费调用、账户核验、预算root配置、DB迁移、生产启用或commit/push。D仍planning。此前独立规划复核对应内部实现三稿；新增授权不证明计费硬限制已接线或live已验收。

现有 `budget.py:29-35` 为root/period/cap_units；`docs/architecture/database-schema.md:680-699` 描述跨job预留/unknown/结算。可复用此基础，但不是已完成的跨provider人民币总账。不为本授权创建冗余协调任务，不修改全局memory。
