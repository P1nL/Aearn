# 03 Desktop Learning Experience Completion Design

## Scope Boundary

This child owns visible desktop learning-loop completion. It should change desktop UI state, desktop API consumption, and focused API contracts only where needed to make the existing loop coherent.

This child does not own new execution backends, docs grounding, environment doctor, data export/delete/reset, or adaptive exercise generation. Those capabilities must remain represented as deferred or unavailable when shown.

## Architecture

The relevant desktop layers are:

- `aearn/apps/desktop/src/App.tsx` for shell routing, dashboard banners, note drawer lifecycle, and cross-page state.
- `aearn/apps/desktop/src/stores/useAppStore.ts` for bootstrap, dashboard, route, session, onboarding, learning, and review conversation state.
- `aearn/apps/desktop/src/stores/useNotesStore.ts` for note index, drafts, save, drawer state, and agent-draft requests.
- `aearn/apps/desktop/src/stores/useSettingsStore.ts` for editable user preferences.
- `aearn/apps/desktop/src/pages/*` for route-specific UI state and action wiring.
- `aearn/apps/desktop/src/features/learning/*` for generated exercise workbench controls and feedback panes.
- `aearn/apps/desktop/src/components/generative-ui/*` for streamed tool cards.
- `aearn/apps/desktop/src/api.ts` and `types.ts` for frontend API contracts and response guards.

Backend/API changes should stay focused and additive. If the visible issue is caused by missing API payload data, the API should return stable learner-safe metadata rather than making the desktop infer backend decisions.

## User Flow Contracts

### Onboarding and Route Confirmation

The route card is a streamed tool UI. Only the latest `show_learning_route` card can call confirmation. Confirmation must:

1. Require an `onboarding_session_id`.
2. Disable duplicate confirmation while in flight.
3. Display a recoverable error message when confirmation fails.
4. Hand off to `handlePlanCreated`, which starts the next knowledge point if available.

The desktop must not create a plan from stale route tool arguments.

### Dashboard and Resume

Bootstrap and dashboard banners should describe:

- active goal/stage
- current language/course
- today review count
- resume availability
- next entry point type

The desktop may route to review when the backend returns `next_entry_point.type=review`; it must not compute the 72-hour/high-risk rule locally.

### Learning Workspace

The workspace must accept concept-first sessions where `exercise=null`. Generated tool calls own the visible cards:

- `show_concept_intro` for concept summary and lightweight choices
- `show_concept_check_result` for result/repair/actions
- `show_code_exercise` for exercise workbench
- `show_learning_history` for learning-page-only history

The exercise workbench must keep local editing state separate from backend facts. It may track dirty/stale UI state, but run, submit, hint, explain-error, and explanation-check facts come from API responses.

### Exercise Feedback

The UI should split feedback sources:

- runner facts from `RunExerciseResponse`
- scoring facts from `SubmitExerciseResponse.code_completion_result`
- explanation facts from `ExplainErrorResponse`
- explanation-check facts from `ExplanationCheckResponse`

The desktop must not expose internal labels like `Attempt(run)` or hidden test internals to learners.

### Review

Review has a separate session contract but must share the same product language as learning:

- queue loading/error/empty states
- warmup and warmup repair before variant practice
- no FSRS display change until `exercise-result` submission succeeds
- `review_ai_patch` evidence/risk/next-action fields required client-side before submit

This child may improve review exercise presentation, but full runner reuse for review is not required unless already supported by the API.

### Notes

Notes are knowledge-point scoped and shared by learning and review contexts. Closing a drawer with unsaved edits should try to save. If save fails, the drawer remains open and the local draft remains available for retry.

Agent note assistance must be displayed as a draft/suggestion, not silently written as the user's note.

### Settings

Settings should present the seven product categories from the frontend spec:

- appearance
- models
- learning
- review
- notifications
- privacy
- diagnostics

Editable controls in this child are limited to existing user preferences. Settings can show diagnostics for API/session/dashboard state, but environment doctor and runner matrix must remain deferred to later children.

## Data and Compatibility

- Preserve current local bootstrap storage keys and existing restore behavior.
- Preserve current route IDs and public language IDs: `javascript`, `python`, `java`, `cpp`, `html_css`.
- Preserve current API response shapes unless a focused additive field is needed.
- Keep response guards in `api.ts` aligned with backend payloads.
- Keep all hidden tests, raw prompts, provider errors, solution references, and secrets out of the UI.

## Failure and Rollback

- UI-only changes roll back by reverting desktop files under `aearn/apps/desktop/src`.
- API guard changes roll back by reverting `api.ts`/`types.ts` and any matching backend contract tests.
- If a dashboard/resume bootstrap error happens, clear only invalid stored user/plan contexts; do not clear unrelated local state.
- If note save fails, preserve local draft state and keep retry available.

## Trade-Offs

- Prefer focused state and copy improvements over a broad redesign so the child closes product-loop holes without invalidating existing smoke checks.
- Keep later capabilities visible only as deferred boundaries. This avoids overclaiming and keeps the parent task's phased dependency contracts intact.
- Prefer deterministic UI messages after run/submit over extra model calls. This keeps feedback immediate and avoids local scoring.
