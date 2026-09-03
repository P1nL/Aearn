# 学习计划语言语义解析实施计划

## Planning State

本任务为跨 provider contract、Harness decision、planning service、持久请求、Skill 和 QA 的复杂任务。用户已明确批准，2026-09-03 已完成实现与隔离全量验证；当前已持久化的八项请求保持不变，只能在发布后通过既有 cancel/recreate 流程进入 v2。

## Ordered Implementation

### Phase A：Contract and Test Foundations

1. 为 `planning-intent-hint-v2`、language candidate context、resolution precedence和clarification-required先添加纯函数/strict-schema测试。
2. 增加 exact regression phrases：
   - `我想做langchain架构的agent` -> Python semantic shortlist、无 Java、无 auto-confirm。
   - `LangChain4j` -> Java semantic shortlist、人工确认。
   - `我想做一个 Agent` + insufficient hint -> clarification。
   - explicit Python -> deterministic auto-confirm。
3. 为 invalid/duplicate/inactive/stale/extra/over-3 candidates添加fail-closed测试；断言不存在 enabled-mode full catalog。

### Phase B：Server Candidate Context and Provider Schema

4. 在 learning plan context tool 中仅对缺失 `language_id` 投影 bounded active language candidates及safe capability摘要，并调整该字段的model descriptor：有候选时使用exact planning question，无可靠候选时允许一个定向clarification；其他字段规则不变。
5. 扩展 provider wait-for-input strict schema、generated output schema、parser和 `TutorDecision`，添加条件化 v2 hint。
6. 更新 provider repair提示和fake Codex/App Server fixtures，确保低置信走 clarification，高/中置信返回1..3候选。

### Phase C：Resolver, Gate, and Persistence

7. 升级 `PlanningIntentResolver` policy v2：保留 explicit auto-confirm，接入 validated semantic hint，新增 `clarification_required`，移除 enabled-mode `no_intent_signal -> full_catalog`。
8. 在 `PlanningQuestionDecisionGate` 校验 current candidate set、session/input revision、candidate bounds和hint/action组合。
9. 在 persistence unsafe boundary 重算并构建exact narrow presentation；复用 `intent_shortlist` public scope和new safe reason codes。
10. 保证 clarification response不写 language fact，下一fresh turn重新解析。

### Phase D：Skill and Compatibility

11. 新增 `tutor.learning-plan-draft/1.0.2`，不修改1.0.1；更新policy resolver到1.0.2，并扩展Skill Catalog tests/hash期望。
12. 保留 v1 hint/history/full-catalog request读取；feature-off路径明确作为legacy rollback。
13. 验证当前 pending request未变化；代码验证后再通过现有取消/新建流程获得v2 request。

### Phase E：Desktop, Docs, and Integration

14. 更新API/architecture/frontend interaction/source-of-truth QA文档；更新Trellis code-spec。
15. 补充API snapshot/request、SSE/history replay和Desktop radio交互测试；无UI代码变更时不创建新组件。
16. 使用fake provider跑当前LangChain场景，断言public snapshot只包含Python option、recommended null和safe reason metadata。

## Expected Write Scope

- `aearn/services/api/app/services/learning/planning_intent.py`
- `aearn/services/api/app/services/learning/plan_tools.py`
- `aearn/services/api/app/services/learning/planning_questions.py`
- `aearn/services/api/app/services/learning/planning_facts.py`
- `aearn/services/api/app/services/tutor/decision_protocol.py`
- `aearn/services/api/app/agents/harness/contracts.py`
- `aearn/services/api/app/services/tutor/persistence/interaction.py`
- `aearn/services/api/app/services/learning/plan_policy.py`
- new `aearn/services/api/app/agents/skills/tutor.learning-plan-draft/1.0.2/**`
- focused API/Codex/Tutor/Desktop tests and source-of-truth docs/specs

实现前必须重新检查 dirty ownership；当前大量 Trellis/generated/Skill 旧版本修改属于并行工作，不得重置、覆盖或批量normalise。若预期文件已被其他窗口修改，先按文件/行范围协调而不是清理工作树。

## Validation Commands

```powershell
uv --directory ./aearn/services/api run python -m pytest tests/codex_sidecar/test_codex_learning_plan_tools.py -q
uv --directory ./aearn/services/api run python -m pytest tests/codex_sidecar/test_codex_learning_plan_tools_postgres.py -q
uv --directory ./aearn/services/api run python -m pytest tests/tutor/test_tutor_interaction_requests.py -q
uv --directory ./aearn/services/api run python -m pytest tests/learning/test_learning_plan_sessions.py -q
uv --directory ./aearn/services/api run python -m pytest tests/tutor/test_tutor_skill_catalog.py -q
uv --directory ./aearn/services/api run ruff check app tests
uv --directory ./aearn/services/api run python -m mypy app --no-incremental
pnpm --dir ./aearn/apps/desktop test
pnpm --dir ./aearn desktop:check
python ./.trellis/scripts/task.py validate 09-03-semantic-planning-language-resolution
git diff --check
```

需要PostgreSQL的测试串行运行。默认fixtures/fake provider，不执行真实provider调用。实现后额外运行raw-byte Skill catalog扫描并检查new1.0.2为LF。

## Review Gates

- Gate 1：模型只能选择server candidates，不能提供label/UUID/options。
- Gate 2：semantic result绝不auto-confirm；explicit language仍可auto-confirm。
- Gate 3：enabled ambiguity无full catalog；低置信有可回答clarification。
- Gate 4：request一旦持久化即immutable/replay exact；历史v1兼容。
- Gate 5：Skill新版本、policy选择、manifest hash和EOL一致。
- Gate 6：无real provider、无当前request静默更新、无无关dirty文件进入提交。

## Rollback

- 关闭现有 planning intent feature flag，恢复明确标记的legacy full-catalog行为。
- policy resolver回退到Skill1.0.1；保留1.0.2和v2 request/history读取。
- 不删除或改写历史request、fact、turn或session。

## Final Planning Review Gate

最终规划摘要已由用户明确批准；实现分支、任务启动、代码变更、测试和质量门禁均已完成。归档前不得把当前历史 pending request 改写为 v2。
