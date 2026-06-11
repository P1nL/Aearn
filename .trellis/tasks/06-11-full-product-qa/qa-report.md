# Full Product QA Report

Date: 2026-06-11
Task: `06-11-full-product-qa`
Status: ready for closeout

## Source Documents Reviewed

- `docs/README.md`
- `docs/product/user-flows.md`
- `docs/product/frontend-interaction-spec.md`
- `docs/architecture/api-contract.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/fsrs-scheduling-spec.md`
- `docs/architecture/langgraph-state-machine.md`
- `docs/qa/acceptance-test-plan.md`
- `docs/setup/development-environment.md`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/error-handling.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/frontend/index.md`
- `.trellis/spec/frontend/quality-guidelines.md`
- `.trellis/spec/frontend/type-safety.md`
- `.trellis/spec/frontend/component-guidelines.md`
- `.trellis/spec/frontend/state-management.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`

## Source-of-Truth QA Notes

- Normal resume path can still point to learning; dashboard may surface review when reset data has high-risk due reviews.
- New desktop review warmup is natural conversation: no visible skip entry, no "warmup stage" copy, and user text `跳过` / `skip` stays `action=answer`.
- Hidden `action=skip` remains backend compatibility only.
- Warmup branches write only `learning_sessions.review_stage_state_json` and review conversation history; they must not create `Attempt`, write `review_logs`, update `ReviewState`, or update FSRS evidence.
- Formal review exercise submit writes `Attempt(review_submit)`; final batch completion is the FSRS update boundary.
- Live-model QA evidence is product/API-level only; this report does not record secrets, raw prompts, hidden tests, raw provider errors, or provider reasoning.

## Command Results

| Area | Command | Result | Notes |
|---|---|---|---|
| Trellis planning | `python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-11-full-product-qa` | PASS | Planning artifacts valid before start. |
| Backend milestone | `uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py -q` | PASS | `32 passed`; ran sequentially before browser/live QA. |
| Backend milestone | `uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py -q` | PASS | `76 passed`; ran sequentially. |
| Backend milestone | `uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py -q` | PASS | `25 passed`; rerun after warmup copy/docs fixes. |
| Backend milestone | `uv --directory .\aearn\services\api run python -m pytest tests/test_notes_m5.py -q` | PASS | `5 passed`. |
| Backend milestone | `uv --directory .\aearn\services\api run python -m pytest tests/test_dashboard_resume_m6.py -q` | PASS | `5 passed`. |
| Backend LLM | `uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py -q` | PASS | `52 passed`; rerun after warmup copy fixes. |
| Backend expanded | plan generation, graph/runtime, runner, local-boundary batches | PASS | `14 passed`, `102 passed`, `48 passed`, `10 passed`; initial stale review graph expectation fixed. |
| Backend focused | `uv --directory .\aearn\services\api run python -m pytest tests/test_review_graph.py -q` | PASS | `13 passed`; confirms `submit_review_batch` route. |
| Backend lint | `uv --directory .\aearn\services\api run ruff check ...` | PASS | Focused affected-file lint passed; earlier broad `ruff check .` passed. |
| Backend type | `uv --directory .\aearn\services\api run python -m mypy app` | PASS | Direct `uv ... mypy app` hit uv script canonicalization; `python -m mypy app` passed. |
| Desktop | `pnpm --dir .\aearn desktop:check` | PASS | `tsc && vite build` passed; known chunk-size warning remains non-blocking. |
| Local runtime | `pnpm --dir .\aearn dev:test-data` | PASS | Reset data and restarted local API/worker/desktop. |
| Local runtime | `pnpm --dir .\aearn dev:status` | PASS | Docker PostgreSQL/Redis healthy; API `8001` and desktop `1420` ready. |

## Browser Smoke Matrix

| Flow | Result | Evidence |
|---|---|---|
| API health | PASS | `GET /health` returned `{status:"ok", service:"aearn-api"}`. |
| Desktop readiness | PASS | `http://127.0.0.1:1420` returned 200 and loaded title `Aearn`. |
| Dashboard/resume | PASS | `/api/dashboard` returned `today_review_count=2`, `next_type=review`; `/api/learning-sessions/resume` returned `next_type=learning_session`. |
| Review natural warmup | PASS | Two due review items visible; new session text uses "先从这个问题开始"; no skip button; no old "先热身/已跳过" visible copy. |
| Typed `跳过` / `skip` | PASS | Browser submitted both as ordinary user messages; UI stayed in answer/repair flow rather than hidden skip action. |
| Notes | PASS | Notes page opens, `AI Patch Review Evidence` note can be selected, Markdown textarea shows existing note, save disabled when unchanged. |
| Settings | PASS | Seven categories visible: 外观、模型设置、学习偏好、复习、通知与提醒、记录与隐私、关于与诊断; no Attempt/FSRS/`review_submit`/`due_at`/score controls exposed. |

## Live-Model QA

| Path | Result | Evidence |
|---|---|---|
| Provider capability | PASS | Config status `configured`, provider `deepseek`, model configured; no secrets printed. |
| Plan generation | PASS | `POST /api/plans/generate` returned 200 with `plan_draft`, 5 dynamic modules, source attribution, and agent notes. |
| Learning concept flow | PASS with retry | `trigger-concept-check` returned `show_concept_intro`; first concept answer returned stable `MODEL_UNAVAILABLE` without internals, second answer produced `agent_message/tool_call/done` with `show_concept_check_result`, follow-up produced `agent_message/done`. |
| Review warmup off-topic | PASS | First off-topic returned `review_stage=warmup`, `next_action=retry_same`, `warmup.result=off_topic`, `judgement_source=llm`, feedback present. |
| Review guided exercise boundary | PASS | Second off-topic returned `review_stage=exercise`, `next_action=start_exercise`, `guided=true`. |

## Data-Safety Checks

| Invariant | Result | Evidence |
|---|---|---|
| Warmup creates no `Attempt` | PASS | After first and second off-topic: `attempts=0`. |
| Warmup writes no `review_logs` | PASS | After first and second off-topic: `review_logs=0`. |
| Warmup does not update long-term `ReviewState` | PASS | `review_states_with_attempt=0`; only session stage state changed. |
| First off-topic stays warmup | PASS | DB stage `warmup`, `off_topic_count=1`, `retry_same`. |
| Second off-topic enters guided exercise | PASS | DB stage `exercise`, `variant.guided=true`, still no Attempt/review_logs. |
| Final review FSRS boundary | PASS | Covered by `tests/test_reviews_m4.py`; formal submit writes review attempts and batch finalization updates scheduler only at completion. |

## Fixes Made During QA

- Fixed stale review graph expectations from `submit_and_update` / `attempt_and_fsrs` to `submit_review_batch` / `review_batch`.
- Fixed `seed_test_data.py` mypy indexing errors with typed `Mapping[str, object]` casts.
- Replaced user-visible review warmup stage copy in desktop and backend history fallback with natural conversation wording.
- Aligned `docs/product/user-flows.md`, `docs/qa/acceptance-test-plan.md`, `docs/architecture/fsrs-scheduling-spec.md`, and `docs/architecture/langgraph-state-machine.md` with the hidden-skip/new-desktop boundary.

## Findings

- Fixed P2: Desktop and persisted review-message fallback still exposed stage-like warmup copy (`先热身`, `热身...`, `已跳过`) despite the natural conversation decision.
- Fixed P2: Several source-of-truth docs still described visible warmup skipping; updated to say desktop does not expose skip and `action=skip` is hidden compatibility only.
- Observation: One live learning concept answer returned recoverable `MODEL_UNAVAILABLE`; retry succeeded and no provider internals leaked. Treat as model-path flakiness to monitor, not a blocker for this local QA pass.

## Final Verdict

PASS after contained fixes. Current remaining risk is the known Vite chunk-size warning and normal live-model variability; no P0/P1 blocker found after rerun.
