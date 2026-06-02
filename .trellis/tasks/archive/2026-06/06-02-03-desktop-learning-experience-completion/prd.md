# 03 Desktop Learning Experience Completion

## Goal

Close the highest-impact visible gaps in the local desktop learning loop so a learner can move from an active route into learning, practice, review, notes, and settings without prototype dead ends or misleading capability states.

## User Value

- Learners can understand where they are in the route and resume the next useful step.
- Learning and review exercise interactions expose clear loading, stale, unsupported, retry, and feedback states.
- Notes remain trustworthy during learning and review, including save failures.
- Settings explain local product boundaries without overclaiming runner, environment doctor, or data-management capabilities that belong to later children.

## Confirmed Facts

- The desktop app is under `aearn/apps/desktop`.
- The visible shell already includes `OnboardingPage`, `LearningWorkspacePage`, `ReviewPage`, `NotesPage`, and `SettingsPage`.
- API helpers already cover onboarding messages, plan confirmation, dashboard, resume, learning session start/messages, run/submit/hint/explain/check, reviews, notes, and user preferences.
- The product spec for this child is primarily `docs/product/frontend-interaction-spec.md`; the manual QA baseline is `docs/qa/acceptance-test-plan.md`.
- Learning exercises are rendered through generated tool UI in the conversation, not through a separate fixed IDE page.
- `compiled_sandbox_later` must remain non-executable in the visible UI.
- Environment doctor, official docs grounding, new runners, local export/delete/reset, and adaptive exercise generation are owned by later child tasks.

## Requirements

- Keep onboarding route confirmation honest: only the newest route card can start, confirmation has loading/error feedback, and API offline or missing session states do not silently fail.
- Improve dashboard/resume visibility so users can see current learning, review count, resume availability, and the next available action from every post-onboarding route where it matters.
- Improve learning exercise action states: run/preview/submit/hint/explain/check must have clear disabled reasons, retry behavior, stale result warnings, and deterministic post-action feedback without local scoring.
- Improve review flow consistency: warmup, variant practice, `review_ai_patch`, and submission result states must be visible and must not imply FSRS updates before backend submission.
- Improve notes affordances: note drawer/page should preserve local edits on save failure, show retry state clearly, and avoid closing silently when save fails.
- Improve settings diagnostics copy and categories so the page reflects the current local-only product while clearly deferring environment doctor, runner availability matrix, data export/delete/reset, and install guidance to later tasks.
- Keep UI capability disclosures aligned with current runtime contracts: Java/C++ static-only, Python/browser paths executable only where backend runtime profile says so, and TypeScript/Go/C#/SQL not presented as executable in this child.
- Add or update focused checks where practical, preferring desktop build/type checks and API tests that protect the UI contracts being changed.

## Acceptance Criteria

- [ ] `pnpm --dir .\aearn desktop:check` passes.
- [ ] Focused backend/API tests for dashboard, onboarding, learning sessions, reviews, notes, and/or user preferences pass when affected.
- [ ] A learner can start from an existing active plan, see the current/resume/review prompt, open a knowledge point, and interact with the learning conversation without prototype-only empty states.
- [ ] Exercise UI clearly distinguishes preview/run, visible tests, submit, stale results, unsupported runtime, retryable API errors, hints, explain-error, and explanation-check states.
- [ ] Review UI clearly distinguishes empty queue, loading, warmup, warmup repair, variant practice, `review_ai_patch`, submitted result, and failed submission states.
- [ ] Notes drawer/page do not lose unsaved local edits when save fails, and the user can retry saving.
- [ ] Settings page includes the seven expected categories and does not expose controls for backend scoring rules, FSRS internals, Attempt persistence, runtime installation, data export/delete/reset, or environment doctor features before their owning children.
- [ ] No UI text claims TypeScript, Go, C#, Rust, SQL, Java, or C++ L3 execution support beyond current backend capability.

## Out of Scope

- New language runner implementation or runtime registry changes.
- Official/trusted documentation grounding, citation metadata, or learning-agent grounding integration.
- Environment doctor/toolchain detection and install guidance.
- Local data export/delete/reset.
- Adaptive exercise generation and validation.
- Major visual redesign or replacing the current app shell.
- Cloud deployment, SaaS accounts, telemetry, or packaging installers.

## Open Questions

- None blocking. The user has asked to continue directly in order; this child should proceed after planning artifacts are complete and validated.
