# 学习计划语言语义解析技术设计

## 1. Architecture Boundary

```text
learner input
  -> deterministic explicit-language extraction
       -> one explicit active language: append confirmed fact
       -> otherwise continue Tutor run
  -> planning context tool exposes server-built active language candidates
  -> model emits one strict action
       -> planning_input(language_id + semantic hint v2)
       -> clarification(no language hint)
  -> PlanningQuestionDecisionGate validates current run/session/candidates
  -> PlanningIntentResolver revalidates against active PostgreSQL catalog
  -> persist exact narrow presentation or clarification request
  -> Desktop renders persisted request without local inference
```

模型拥有语义匹配，不拥有课程、option label、事实写入或发布 authority。确定性 explicit path 保持最优先，语义 path 永不 auto-confirm。

## 2. Server-Built Candidate Context

当 `next_missing_fact.field_key == language_id` 时，`aearn_planning_context_read` additive 返回 bounded `language_candidates`：

```json
[
  {
    "language_id": "python",
    "course_title": "Python Basic Beginner",
    "level": "beginner",
    "capability_state": "full",
    "execution_family": "python_stdout_test"
  }
]
```

只投影 active published course language 和 learner-safe capability metadata；不发送 course UUID、source、命令、路径、runner 配置或密钥。列表由服务器排序且有界，模型不能请求扩展。

同时更新 `language_id` 的 model descriptor：有 validated shortlist 时仍逐字使用服务器 exact planning question；证据不足时允许改走 `clarification` 并生成一个定向问题。其他 planning fact 继续遵守现有 exact-question 规则，不能借此提出第二个问题。

## 3. Provider Contract v2 Hint

在 `TutorProviderWaitForInputItem` 上增加仅限语言 planning request 的 closed payload：

```json
{
  "type": "wait_for_input",
  "continuation_kind": "planning_input",
  "question_key": "language_id",
  "planning_intent_hint": {
    "schema_version": "planning-intent-hint-v2",
    "candidate_language_ids": ["python"],
    "confidence": "high",
    "reason_code": "technology_ecosystem_match"
  }
}
```

约束：

- `candidate_language_ids` 长度 1..3、unique、canonical；只能引用当前 tool context 候选。
- `confidence` 为 `high | medium`；low/insufficient 不允许创建 language planning request，模型改用 `clarification`。
- `reason_code` 使用 closed union，如 `technology_ecosystem_match | goal_domain_match | runtime_compatibility_match | mixed_semantic_match`。
- Hint 只允许 `planning_input + question_key=language_id`；其他 action/question extra-forbid。
- Provider schema、parser、`TutorDecision` 添加 exact typed field；旧 v1 provider history 不需要重写。

## 4. Resolution Precedence

`PlanningIntentResolver` v2 使用固定优先级：

1. 一个明确 active language -> `auto_confirm`，仅该路径写 confirmed fact。
2. 多个明确语言、明确语言/方向冲突 -> existing explicit/conflict shortlist。
3. 确定性方向标签有 active courses -> deterministic intent shortlist。
4. 有通过校验的 v2 semantic hint -> semantic shortlist，1..3 项，人工确认。
5. 否则 -> `clarification_required`，candidate list 为空；禁止 full catalog。

`enabled=false` 保留 legacy full catalog，reason code 必须为 rollback/disabled，不与 ambiguity fallback 混淆。现有 v1 closed tag hint可兼容读取，但新 Skill 只发布 v2。

## 5. Decision Gate and Persistence

`PlanningQuestionDecisionGate` 对 language planning request：

- 加载 active planning session、current input revision 和 active course catalog。
- 结构化校验 hint，并验证 language values 均属于当前 server candidate set。
- 重新运行 resolver；若结果为 `clarification_required`、invalid/stale/empty hint，则 deny safe diagnostic，不允许 persistence 构建 full catalog。
- 通过后才记录 question asked。

`record_interaction_request` 在 unsafe boundary refresh 后再次解析 exact learner input + decision hint，防止 catalog/state TOCTOU；只从 active rows构建 labels和顺序。Presentation 继续使用：

```json
{
  "type": "single_select",
  "field_key": "language_id",
  "options": [{"value": "python", "label": "Python Basic Beginner"}],
  "recommended": null,
  "selection_scope": "intent_shortlist",
  "selection_reason_code": "semantic_technology_ecosystem_match",
  "intent_policy_version": "planning-language-intent-v2"
}
```

不新增 DB 列；exact presentation 已由 `presentation_json`、descriptor hash 和 request version 持久化。Public 只见 safe metadata，不见 confidence 或 model rationale。

## 6. Clarification Behavior

模型在低置信、无候选或候选接近时使用现有：

```json
{"type":"wait_for_input","continuation_kind":"clarification"}
```

Public message 只问一个定向问题，例如确认框架变体、运行环境或希望使用的实现语言。Clarification response 作为 fresh learner turn，下一次 resolver重新处理；它不写 `language_id` fact。

新 Skill 明确禁止：在没有 explicit/deterministic/validated semantic candidates 时请求 `planning_input(language_id)`。若模型违反，decision gate fail closed；不得用 full catalog 掩盖错误。

## 7. Skill and Policy Versioning

- 新增 immutable `tutor.learning-plan-draft@1.0.2`，更新 instructions/evals/manifest hashes。
- `InteractiveLearningCapabilityPolicyResolver` 选择 1.0.2。
- 1.0.0/1.0.1 保留 catalog/history compatibility，不原地编辑。
- 本任务基于 `codex/tutor-skill-catalog-eol-regression`，确保新 bundle 的 LF raw-byte规则已存在。

## 8. Desktop and Public Compatibility

复用现有 `single_select` 与 `text clarification` 组件，不新增新 UI primitive。`intent_shortlist`、nullable recommendation 和 open safe reason code 已在 API/Desktop DTO 中存在，因此正常实现不需要扩展 public scope union。

验证重点：1..3 options、zero initial selection、disabled Submit、sessionStorage draft identity、snapshot/SSE/history exact replay、narrow viewport无溢出。若实现没有修改 Desktop 代码，仍补充 API contract fixture和现有组件回归；若 DTO 发生变化则同步 parser/type tests。

## 9. Existing Request and Rollback

已经持久化的八项 request 不更新。实现验证完成后使用现有取消计划流程关闭当前 session，再新建计划会话；新 request 才应用 v2。Rollback 关闭 intent feature后恢复 legacy full catalog，不删除历史 request/fact/turn。

## 10. Risks and Mitigations

- 模型语义不稳定：只允许 active候选、最多3项、用户确认、fake-provider fixtures和decision gate二次校验。
- 模型忽略 hint contract：strict schema + Skill eval + fail closed；不以全目录恢复。
- 候选目录在模型调用期间变化：unsafe-boundary refresh后重算并验证。
- 模糊输入可能反复澄清：每次只问一个高信息量问题，并保留 conversation context；加入bounded重复测试。
- 新 Skill EOL/hash：继承 `.gitattributes` 规则并运行全 catalog raw-byte扫描。
