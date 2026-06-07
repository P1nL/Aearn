# Technical Design: Learning Flow Concept Checks and Official Docs Panel

## Scope

This task refines an existing learning-page flow across backend contracts, frontend rendering, and product docs:

- Replace the current multi-section teaching document panel with a two-section official-docs panel.
- Keep `show_concept_check_result` as a persisted tool event but render it as compact feedback instead of a large card.
- Tighten concept judgement semantics for `unclear`.
- Add follow-up limits for both `incorrect` and `unclear`.
- Prevent answer leakage where the model reveals the answer and then asks the learner to repeat it.

The task should build on existing code in `aearn/`; do not reintroduce historical tutorial directories.

## Current Code Facts

- Frontend learning page: `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx`.
- Documentation panel component: `aearn/apps/desktop/src/components/DocumentationPanel.tsx`.
- Frontend types and guards: `aearn/apps/desktop/src/types.ts`, `aearn/apps/desktop/src/api.ts`.
- Concept result rendering currently uses `show_concept_check_result` tool calls in `LearningWorkspacePage.tsx`.
- Documentation API: `GET /api/learning-sessions/knowledge-points/{knowledge_point_id}/documentation`.
- Documentation backend assembly: `aearn/services/api/app/services/repositories/learning_session_repository.py`.
- Current documentation source fields: `knowledge_points.lesson_outline_json`, `lesson_sources_json`, `teaching_chunks`.
- Concept judgement agent: `aearn/services/api/app/agents/learning/learning_concept_agent.py`.
- Learning conversation transition logic: `aearn/services/api/app/services/conversations/learning_conversation.py`.
- Structured judgement normalization: `aearn/services/api/app/agents/runtime/structured_judgement.py`.

## Documentation Panel Contract

### Response Shape

Reuse the existing documentation endpoint, but change the semantic payload to two stable section types:

```json
{
  "knowledge_point_id": "kp_...",
  "title": "字符到 double 的数值转换",
  "summary": "官方文档片段和示例。",
  "sections": [
    {
      "id": "official_documentation",
      "type": "official_documentation",
      "title": "官方文档内容",
      "content_markdown": "...",
      "code_blocks": []
    },
    {
      "id": "examples",
      "type": "examples",
      "title": "实例",
      "content_markdown": "...",
      "code_blocks": [
        {
          "language": "java",
          "code": "double z = 'A';",
          "caption": "Aearn 示例：验证 char 转 double 时使用字符编码数值。",
          "source_type": "aearn"
        }
      ]
    }
  ],
  "references": [
    {
      "title": "Java Language Specification",
      "url": "https://docs.oracle.com/...",
      "source_type": "official",
      "retrieved_at": "2026-06-06T00:00:00Z"
    }
  ],
  "generated_at": "2026-06-06T00:00:00Z",
  "cache_hit": false
}
```

If adding `source_type` to code blocks/references is too broad for the first pass, keep it in `metadata` or derive the visible label from section content. The UI requirement remains: official examples and Aearn examples must be distinguishable.

### Source Strategy

Recommended staged implementation:

1. Use `lesson_sources_json` to identify official/trusted URLs already attached to the knowledge point.
2. Use existing `teaching_chunks` and source notes only as retrieval aids, not as compressed final document text.
3. Prefer official localized pages when the URL set already points to a localized page.
4. When only non-localized official pages exist, translate the smallest relevant excerpt into the user-facing language.
5. Keep original source attribution visible.

Do not store or present full official pages as copied local mirrors. Cache only the generated/translated target excerpt for the knowledge point, with source URL and timestamp.

### Translation Boundary

Allowed:

- Faithful translation.
- Formatting cleanup.
- Terminology consistency.
- Code block preservation.
- Short labels that identify source type.

Not allowed:

- AI summarization that removes official details.
- AI rewriting into a different teaching sequence.
- Combining multiple sources without showing provenance.
- Presenting Aearn-generated examples as official examples.

## Concept Result UI

Backend keeps the existing tool call:

```text
show_concept_check_result
```

Frontend changes only rendering:

- Hide the large standalone card.
- Render a compact feedback block inside the Agent message.
- Preserve quick replies/actions when present.
- Preserve metadata for persisted history and recovery.

Recommended compact shape:

```text
判断：还需要补一点
原因：B 正确，但 C 也成立；你漏掉了 char 到 double 的数值转换。
下一步：换一个字符判断，或进入引导练习。
```

If the tool call appears in historical messages, it must render consistently as compact feedback, not as the old large card.

## Judgement Semantics

Update the concept agent prompt and response contract:

- `unclear` means the model cannot determine the learner's position.
- `incorrect` covers wrong, incomplete, or partially correct answers.
- A learner selecting only part of a multi-answer set is not `unclear`; it is incomplete/incorrect with a clear missing point.
- Repeated same-answer user messages should not trigger repeated clarification.

If a distinct `incomplete` enum would create too much API churn, keep public `result` as `incorrect` and express incompleteness in `explanation` / `next_prompt`.

## Follow-Up Limit

Current code increments `concept_check_attempts` for `incorrect`, but not reliably for `unclear`.

Design change:

- Count both `incorrect` and `unclear` as concept-check attempts.
- Use a shared limit, recommended `2`.
- Once limit is reached:
  - Remove `repair_check`.
  - Provide actions: `进入引导练习`, `再看一个例子`.
  - Set `repair_limit_reached=true` or equivalent stage state.
  - Do not ask another "更具体一点" clarification question.

This should apply whether `unclear` comes directly from model `result` or from `judgement_ready=false` normalization.

## Answer Leakage Contract

Do not add deterministic backend answer rewriting for this task. The backend should not encode language-specific facts such as `A -> 65`, should not scan for known answers like `65.0`, and should not replace the model's teaching text with a hardcoded fallback.

Instead, make answer leakage part of the concept agent's explicit output contract.

### Agent Self-Check

Extend the concept-check result schema with a model-produced self-check section:

```json
{
  "result": "correct | incorrect | unclear",
  "confidence": "high | medium | low",
  "explanation": "learner-facing feedback",
  "next_prompt": "next learner action",
  "answer_leakage_review": {
    "status": "clear | revised",
    "revealed_target_answer": false,
    "next_prompt_requires_same_answer": false,
    "reason": "short explanation"
  }
}
```

Rules for the agent:

- Before returning final JSON, inspect its own `explanation` and `next_prompt`.
- If it revealed the value/option/code fragment that `next_prompt` asks for, it must revise the final `next_prompt`.
- Valid revisions are transfer checks, reason checks, or practice offers.
- The final payload should have `answer_leakage_review.status` as `clear` or `revised`.
- `revised` means the agent caught and fixed its own leakage before the payload reached the UI.

The backend validates only the structure and allowed enum values. It may persist `answer_leakage_review` for observability, but it does not rewrite `explanation`, does not rewrite `next_prompt`, and does not infer target answers.

### Tests

Tests should verify the contract rather than backend hardcoding:

- The prompt/schema asks the agent to perform `answer_leakage_review`.
- Mocked final payloads can include `answer_leakage_review.status="revised"` with a transfer/practice prompt.
- The user-reported `double z = 'A'` / `65.0` scenario should be represented as a mocked agent final response where the agent has already revised the prompt away from "repeat 65".
- There should be no deterministic backend test that expects Python/Java-specific value matching such as `65` / `65.0`.

## Documentation Updates

Update source-of-truth docs after implementation planning is accepted:

- `docs/product/frontend-interaction-spec.md`
- `docs/architecture/api-contract.md`
- `docs/architecture/langgraph-state-machine.md` if learning stage behavior changes
- `docs/qa/acceptance-test-plan.md`

Remove or revise old language that says documentation panel uses five standard sections or AI-generated compressed teaching docs.

## Compatibility

- Keep existing endpoint paths unless a schema change requires versioning.
- Keep `show_concept_check_result` tool event name.
- Keep existing persisted messages readable; only frontend presentation changes.
- Avoid DB schema changes unless adding explicit source metadata is required.

## Risks

- Copyright/provenance risk if implementation copies too much official documentation without clear source attribution.
- Regression risk in persisted tool replay if UI assumes all `show_concept_check_result` calls are cards.
- Model behavior may still leak answers because this task intentionally avoids backend answer rewriting; tests and manual review must verify the agent self-check contract stays effective.
- Dynamic official-doc translation may require network and model config; MVP should degrade clearly when unavailable.
