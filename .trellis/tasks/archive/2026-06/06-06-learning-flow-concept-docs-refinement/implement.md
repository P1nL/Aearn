# Implementation Plan: Learning Flow Concept Checks and Official Docs Panel

## Preconditions

- Do not start implementation until this task is moved from `planning` to `in_progress`.
- Keep this task in planning until the user reviews `prd.md`, `design.md`, `implement.md`, and `review.zh.md`.
- Before editing code, load `trellis-before-dev` and relevant spec guides:
  - `.trellis/spec/frontend/index.md`
  - `.trellis/spec/backend/index.md`
  - relevant guide files listed by those indexes.
- Preserve unrelated working-tree changes. The repository already has uncommitted changes in learning-page and backend files.

## Phase 1: Contract and Docs Alignment

1. Update `docs/product/frontend-interaction-spec.md`.
   - Replace five-section documentation panel language with two sections: `官方文档内容`, `实例`.
   - State that official docs are localized/translated faithfully, not AI-compressed.
   - State that `show_concept_check_result` renders compact feedback, not a standalone large card.
2. Update `docs/architecture/api-contract.md`.
   - Document the two-section documentation response.
   - Document source attribution fields and example source labels.
   - Clarify concept judgement semantics and follow-up limit.
3. Update `docs/qa/acceptance-test-plan.md`.
   - Add checks for no answer leakage.
   - Add checks for `unclear` boundaries.
   - Add checks for compact concept feedback rendering.

Validation:

```powershell
rg -n "核心概念|语法结构|实战示例|常见错误|最佳实践|show_concept_check_result" docs aearn\apps\desktop\src aearn\services\api\app
```

## Phase 2: Backend Documentation Payload

1. Inspect current documentation response model in `aearn/services/api/app/models/learning_sessions.py`.
2. Update section typing/serialization to support:
   - `official_documentation`
   - `examples`
   - optional source labels for official/Aearn examples.
3. Modify `get_knowledge_point_documentation()` and helpers in `learning_session_repository.py`.
   - Return exactly two main sections.
   - Use persisted `lesson_sources_json` for references.
   - Keep source URL and timestamp.
   - Avoid AI summarization in this layer.
4. If translation is implemented in this pass:
   - Use existing OpenAI-compatible abstraction.
   - Make translation faithful and source-bound.
   - Fail clearly or fall back to original official text if model unavailable, depending on contract decision.

Backend tests:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
```

Add or update tests for:

- Documentation response has exactly two main section IDs.
- References include source URL/title.
- Aearn examples are not labeled official.
- Payload does not include hidden tests, solution references, raw prompts, or provider payload.

## Phase 3: Agent Concept Judgement Contract

1. Update `aearn/services/api/app/agents/learning/learning_concept_agent.py`.
   - Prompt: define strict `unclear` boundaries.
   - Prompt: partial/missing answers should become `incorrect` with missing point, not `unclear`.
   - Prompt: do not reveal target answer in `explanation` if `next_prompt` asks for it.
   - Add an `answer_leakage_review` self-check field to the model output schema.
   - Instruct the agent to revise its own `next_prompt` before final output when it detects answer leakage.
2. Update `aearn/services/api/app/services/conversations/learning_conversation.py`.
   - Count `unclear` as a concept-check attempt.
   - Apply the same max attempt behavior to `incorrect` and `unclear`.
   - Ensure `judgement_ready=false` unclear paths also count toward the limit.
   - Preserve `answer_leakage_review` metadata if present.
   - Do not add deterministic backend answer rewriting or language-specific value matching.
3. Add tests in existing learning-session/conversation test files.
   - User answers with core rule but not numeric value; model cannot force leaked numeric repetition.
   - Mocked agent final payload for the `65.0` scenario uses `answer_leakage_review.status="revised"` and a transfer/practice prompt, not a repeat-the-answer prompt.
   - Partial multi-answer response is not `unclear`.
   - Two unclear/incorrect attempts stop clarification loop.

Backend tests:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_llm_integration.py
```

## Phase 4: Frontend Compact Concept Feedback

1. Inspect current generative UI rendering in `LearningWorkspacePage.tsx` and `aearn/apps/desktop/src/components/generative-ui/`.
2. Replace large `show_concept_check_result` card rendering with compact inline feedback.
3. Preserve quick replies/actions.
4. Ensure historical/persisted messages render compactly after refresh.
5. Remove or simplify CSS specific to the old large judgement card if unused.

Frontend validation:

```powershell
pnpm --dir .\aearn desktop:check
```

Manual browser/app validation:

- Run the desktop dev flow if available.
- Reproduce a concept-check result and confirm no large card appears.
- Confirm quick replies still work.

## Phase 5: Frontend Official Docs Panel

1. Update `DocumentationPanel.tsx`.
   - Render two main sections.
   - Remove five-section default assumptions and fold states.
   - Show source title, URL, timestamp, and original source entry.
2. Update `DocSection` or equivalent section renderer.
   - Support official/Aearn example labels.
   - Preserve code blocks and source captions.
3. Update `api.ts` guards/types if backend schema changes.
4. Update styles in `styles.css`.
   - Keep current visual language.
   - Avoid adding new dependencies.

Validation:

```powershell
pnpm --dir .\aearn desktop:check
```

Manual validation:

- Enter a knowledge point.
- Right panel shows only `官方文档内容` and `实例`.
- Source labels are visible.
- No five-section generated teaching layout remains.

## Phase 6: Final Verification

Run the narrow backend and frontend checks:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_llm_integration.py
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-06-learning-flow-concept-docs-refinement
```

If changes touch broader API contracts, also run:

```powershell
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run mypy app
```

## Rollback Points

- Documentation panel schema can roll back by preserving the endpoint path and restoring old section construction.
- Concept result UI can roll back independently because backend tool event name is unchanged.
- Concept judgement changes should be guarded by tests before and after prompt changes; do not add deterministic backend answer rewriting unless the product decision is reopened.

## Files Likely Touched

- `docs/product/frontend-interaction-spec.md`
- `docs/architecture/api-contract.md`
- `docs/qa/acceptance-test-plan.md`
- `aearn/services/api/app/models/learning_sessions.py`
- `aearn/services/api/app/services/repositories/learning_session_repository.py`
- `aearn/services/api/app/agents/learning/learning_concept_agent.py`
- `aearn/services/api/app/services/conversations/learning_conversation.py`
- `aearn/services/api/tests/test_learning_sessions_m3.py`
- `aearn/services/api/tests/test_llm_integration.py`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx`
- `aearn/apps/desktop/src/components/DocumentationPanel.tsx`
- `aearn/apps/desktop/src/styles.css`
