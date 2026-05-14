# Technical Design

## Scope Boundary

This task extends the implemented M1/M2 baseline inside `aearn/` only:

- Backend: `aearn/services/api/`
- Desktop: `aearn/apps/desktop/`

Historical tutorial directories remain untouched.

Confirmed scope is full M3 for the learning-session runtime UI:

- `M3-BE-01` start learning session
- `M3-BE-02` runtime boundary for `browser_preview`, `python_stdout_test`, and `compiled_sandbox_later`
- `M3-BE-03` persist `Attempt(run)` plus runner facts
- `M3-BE-04` persist `Attempt(submit)` plus evaluation result
- `M3-AGENT-01` deterministic `hint` / `explain-error` / `check-explanation` endpoints
- `M3-FE-01` generated exercise UI
- `M3-FE-02` stale / loading / error / retry / disabled interaction states
- `M3-QA-01` broader M3 acceptance coverage for UF-04 / UF-05 / CE-01~CE-10 relevant backend cases

Deferred items remain outside M3:

- M4 review queue and full FSRS workflow
- M5 note-assist product completion
- M6 dashboard/resume routing and final acceptance hardening

## Backend Shape

Keep learning-session behavior behind repository/service boundaries:

```text
aearn/services/api/app/
  models/
    learning_sessions.py
  routes/
    learning_sessions.py
  services/
    exercise_repository.py
    exercise_guidance.py
    learning_session_repository.py
    runtime_runner.py
    evaluation.py
```

### Start Session

`POST /api/learning-sessions/start`:

1. Validates `user_id`, `plan_id`, `knowledge_point_id`
2. Reuses an active `LearningSession(session_type=learn)` only when the existing `entry_point` matches the same knowledge point
3. Resolves or seeds one deterministic `Exercise`
4. Returns `session_id`, `context_snapshot`, `exercise`, `initial_agent_message`, and `session_state`

### Runner Boundary

`run_exercise(runtime_profile, exercise, code, filled_blanks, run_mode) -> RuntimeExecutionResult`

Behavior:

- `browser_preview`
  - supports both `preview` and `visible_tests` requests
  - returns preview HTML and test summary
  - includes a hidden-summary failure path so stale state / explain-error flows are reachable without leaking hidden source
- `python_stdout_test`
  - validates parse/runtime shape
  - returns stdout plus test summary
- `compiled_sandbox_later`
  - returns `runtime_status=unsupported`
  - persists `Attempt(run)` but never pretends execution succeeded

### Guidance Layer

`exercise_guidance.py` provides deterministic full-M3 assist responses:

- `build_hint_response(...)`
- `build_error_explanation_response(...)`
- `build_explanation_check_response(...)`

This keeps prompt-like guidance logic out of routes and lets repository code focus on:

- entity lookup
- idempotency
- `Attempt` updates
- response persistence

### Persistence Rules

`run` path:

- idempotency key: `session_id + exercise_id + code_hash + run_mode`
- writes one `Attempt(run)` per unique payload
- persists `runtime_status`, test summary, stdout/stderr, and initial `error_count`
- never updates `ReviewState`

`hint` / `explain-error` / `check-explanation` paths:

- attach to an existing run Attempt
- use idempotency keys derived from attempt plus blank/round/hash
- update:
  - `Attempt.hint_usage_count`
  - `Attempt.error_cause`
  - `Attempt.explanation_text`
  - `Attempt.explanation_check_result`

`submit` path:

- requires a prior run Attempt
- reuses stored run facts when payload matches, otherwise reruns visible tests conservatively
- carries forward the higher of client-reported and stored `hint_usage_count` / `error_count`
- prefers stored `explanation_check_result` when explanation text still matches
- writes `Attempt(submit)` with score, score breakdown, `code_completion_result`, `fsrs_rating`
- updates:
  - `knowledge_points.last_exercise_result`
  - `knowledge_points.last_exercise_score`
  - `knowledge_points.last_exercise_breakdown_json`
  - `knowledge_points.last_explanation_check_result`
  - `knowledge_points.last_session_id`
  - `review_states.last_attempt_id`
  - `review_logs`

### Evaluation Strategy

Follow `docs/architecture/code-completion-evaluation-spec.md` using deterministic fallback logic:

- runtime/test evidence is primary
- explanation-check result becomes part of the hard gate when `requires_explanation=true`
- `hint_usage_count` and `error_count` can downgrade `fsrs_rating`
- hard failures:
  - runtime failure -> `failed`
  - core blank failure -> `failed`
  - explanation failure after passing tests -> `partial`

## Desktop Shape

`aearn/apps/desktop/src/App.tsx` remains the host shell, but the learning page now renders a richer generated workbench.

Primary additions:

- separate actions for `运行预览` and `运行可见测试`
- hint target + hint level controls
- explain-error button
- explanation input + focus + round-tracking
- explanation-check result card
- hint history card
- stale / loading / recoverable error / retry affordances

### UI State Model

- `pristine`
- `dirty`
- `running`
- `submitted`
- `unsupported`

Additional local state:

- `lastRunMode`
- `hintUsageCount`
- `errorCount`
- `hintHistory`
- `explainErrorResult`
- `explanationText`
- `explanationCheckResult`
- `lastExerciseAction` for retry

## Testing Strategy

Backend:

- extend `test_learning_sessions_m3.py`
- cover:
  - session reuse and distinct knowledge points
  - JS success and submit
  - hint idempotency
  - hidden-summary failure + explain-error
  - Python runtime error + explain-error
  - explanation round limit and submit downgrade
  - 3+ hints downgrade `fsrs_rating`
  - core blank failure
  - rollback when submit writes fail mid-transaction

Frontend:

- run `pnpm --dir .\aearn desktop:check`
- browser smoke:
  - open `http://127.0.0.1:1420`
  - generate/confirm a JS plan
  - run visible tests
  - check explanation
  - submit once

## Rollout / Rollback

Rollout:

- backend guidance + repository changes first
- frontend workbench actions second
- tests + browser smoke last

Rollback:

- remove new learning-session assist routes and guidance service
- restore prior M3 minimal workbench behavior
- keep schema columns because they are backward-compatible additive fields already in the local schema flow

## Risks

- `App.tsx` remains large, so prop drift and state drift are the main frontend maintenance risk.
- Deterministic guidance is intentionally conservative; it is good enough for M3 contract verification but not a substitute for later LLM-backed pedagogy.
- Dashboard/resume and review queue remain outside this task, so M3 completion here is scoped to the learning-session runtime loop rather than full post-M3 app routing.
