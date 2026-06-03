# Onboarding dynamic route generation 审阅说明

## 目标

把 onboarding 对话里的学习路线卡改成动态生成结果，而不是继续使用 `COURSE_TEMPLATES` 模板。配置缺失、模型不可用、权威文档缺失或生成质量不达标时，不允许静默兜底成模板路线。

## 范围

- `POST /api/onboarding/messages` 路线卡生成接入动态生成能力。
- `/api/plans/generate` 与 onboarding 使用同一套动态生成契约。
- 补齐 `AUTHORITATIVE_DOCS` 对 `sql` 和 `csharp` 的映射，并测试所有 public supported languages 覆盖完整。
- 增加质量门禁，拒绝没有覆盖用户需求或缺少权威来源的模型输出；不强制固定 modules / knowledge_points 数量。
- 更新 `docs/architecture/api-contract.md`，移除旧的 fallback 描述。

## 验收标准

- 完整 onboarding 槽位触发路线卡时，输出来自动态生成结果。
- 动态生成失败时，不发送 `show_learning_route`，不暂存 `plan_draft`，不使用模板兜底。
- `python`、`javascript`、`typescript`、`html_css`、`java`、`go`、`csharp`、`sql` 都有权威文档映射。
- 未覆盖用户目标、水平、方向、节奏或缺少权威来源的模型输出会被测试和质量门禁拒绝。
- C++ 和 Rust 的 unsupported 行为保持不变。

## 关键设计取舍

推荐不要让 onboarding 在后端内部 HTTP 调 `/api/plans/generate`，而是抽出共享的 application service，让两个 route handler 复用同一生成契约。这样更稳定，也更容易测试。

不做模板兜底会让配置问题更早暴露，但也意味着本地或测试环境必须显式 fake 动态生成结果，否则不会出现路线卡。

## 执行顺序

1. 抽取或新增共享动态生成服务。
2. 接入 onboarding 路线卡生成。
3. 补齐权威文档映射和覆盖测试。
4. 收紧动态输出校验，采用“用户需求覆盖 + 权威来源覆盖”门禁。
5. 更新 API contract。
6. 运行 focused backend tests、`ruff` 和 `mypy`。

## 风险

- 旧测试可能依赖 `None` 触发模板 fallback，需要改成 fake 动态输出。
- SSE 错误需要足够清楚，但不能暴露密钥或 provider 原始错误。
- 如果只做结构校验，模型仍可能输出泛泛路线；因此门禁必须验证用户需求覆盖和权威来源覆盖。

## 回滚点

- `aearn/services/api/app/routes/onboarding.py`
- 共享动态生成 service
- `aearn/services/api/app/agents/onboarding/plan_generation_agent.py`
- `docs/architecture/api-contract.md`

## 当前质量门禁决策

不强制固定数量；只要求路线覆盖用户需求且来源权威。实现时应把 `goal_text`、`target_level`、方向或 `profession`、`time_budget` 等输入纳入校验，并要求 `source_urls` 命中对应语言的权威文档映射。
