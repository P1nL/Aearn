# D 真实父规划请求：选中 Skill 上下文完整性修复（2026-09-28）

## 根因与执行接缝

`CatalogContextLoader.load_context` 对已按 run/revision、policy、selection hash 校验的 `tutor.learning-plan-draft@1.0.3` 构造 `catalog:selected:<id>@<version>` SYSTEM source；内容有 id/version、manifest/instruction SHA-256 与完整 instruction。其发布版 `instructions.md` 约 6.8 KB，后半部分含 capability 参数必须是 JSON 字符串、禁止 effect proposal、成功后 `turn_completed` 且不得以 approval 确认草案等约束。此前 Builder 通用 SYSTEM 序列化递归摘要/1200 字符截断，`TutorContextItem` 又使用 1600 字符公共消息上限；即使 source 被选中，实际请求也可能丢失末尾规则。普通 SYSTEM 原本还能被 optional budget 或条数限制静默跳过。真实模型此前已发出 15 次请求但没有有效父草案；这份修复不是对付费调用的验收结论。

已有 capability schema 修复按原逻辑保留：schema 原子 JSON 输出，不截断；若共享 redaction 会修改内容则拒绝；不够 optional budget 则显式 skipped，不能以残缺 JSON 代替。它不是任意文本提权。

## 本次改动与边界

- 仅在 SYSTEM 且 `catalog:selected:` 精确前缀、五个字段精确形状、source id 与 id/version 相符、两枚摘要是合法 SHA-256 十六进制、instruction 内容与 instruction_hash 精确匹配时，按完整 JSON 序列化。普通/伪造不匹配 source 不能绕过 cap。
- 选中 Skill 的原始内容如被通用 `redact_value` 或 harness 敏感字段过滤改写，则拒绝，不传送被改写的“可执行”指令，也不放宽共享秘密策略。最终 ContextItem 对通过完整性检查的选中 Skill 不施加 1600 公共消息截断；普通 prose、消息及其他未信任来源仍走原 sanitizer/上限。
- 选中 Skill 计入 required token，不占 optional token；即使 optional_budget=0 的 planner 预构建也完整保留。超出 token_budget、落在 SYSTEM item limit 后面，或多个 selected source：在构造 request 前抛 `TUTOR_SELECTED_SKILL_UNREPRESENTABLE`，而非静默降级；保留现有完整请求估计、物理输入上限和 provider preflight。
- 校验摘要只确认接缝中的身份与字节完整性，不在 Builder 内重新授权 catalog 选择；选中来源必须仍经过上游 CatalogContextLoader 的 policy/selection 校验。带全套自洽伪造 digest 的任意 `TutorContextInput` 本身不是新的 trust root；不得把 Builder 用作独立 catalog 授权器。未改发布版 Skill、provider_request、公开入口或生产开关。

## 离线证据

- 从真实发布 catalog 加载 `1.0.3` instruction，并导出正式 `LEARNING_PLAN_DRAFT_DESCRIPTOR` schema；与七条 required facts 一起，经既有 `TutorContextBudgetPlanner` 使用 DeepSeek Flash 16384 决策输出、131072 输入上限配置，断言完整 instruction（含末尾 JSON-string/无 approval 规则）、完整 schema、七条 required facts、零截断、必选 Skill/Schema 均 selected、总请求估计不越界。
- 自造长 instruction 的原子保留与 optional_budget=0；紧预算明确抛错；id/version/hash/source-id 不匹配、字段伪装、SYSTEM item limit 挤出和共享 redaction 改写均拒绝；已有 schema 原子/敏感字段测试保留。
- 未做真实模型调用、隔离 DB 或后继冻结验证；真实 C 用途/时间窗可能到期，后续调用前必须重新确认。通过离线完整性测试只解决上下文交付接缝，不能宣称模型将生成合法父稿或 D 完整链通过。

验证：离线专项（context builder/budget、provider gateway、Skill catalog）147 passed；相关四文件 Ruff passed；app Mypy 326 files passed；git diff --check passed。未重跑广回归或付费窗口。
