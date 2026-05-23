# Harden SDK agent QA and release gates

## Goal

Add cross-agent SDK quality gates, contract tests, provider diagnostics, docs/spec updates, and release readiness checks after the teaching, exercise, note, review, and onboarding SDK slices are implemented.

This task closes the application-on-SDK rollout by proving the SDK layer improves Agent behavior without breaking Aearn-owned API contracts, deterministic fallback, durable state ownership, or MVP product boundaries.

## Requirements

- Build a cross-agent verification matrix covering:
  - Teaching Agent messages;
  - Exercise Coach hint/explain/check;
  - Note Assist agent-draft;
  - Review Coach startup/rationale;
  - Onboarding Plan Agent plan-draft generation.
- Ensure every SDK-backed path has model-key-free tests for:
  - fake SDK success;
  - SDK failure;
  - invalid or malformed output;
  - guardrail-blocked leakage;
  - deterministic fallback.
- Add provider/runtime diagnostics only if they can avoid exposing secrets and raw provider payloads.
- Confirm no public JSON/SSE contract leaks SDK event names, tool payloads, provider error bodies, raw prompts, or secrets.
- Confirm durable writes remain in Aearn services/repositories:
  - `Attempt`;
  - `ReviewState`;
  - `ReviewLog`;
  - `Note`;
  - `LearningPlan`;
  - `idempotency_records`.
- Update `.trellis/spec/backend/` or docs only for stable conventions learned during implementation.
- Produce a release-readiness summary with commands run and residual risks.

## Acceptance Criteria

- [ ] Cross-agent SDK test matrix exists in tests, docs, or release report.
- [ ] Full backend pytest passes.
- [ ] Relevant `mypy`, `ruff`, and `uv lock --check` commands pass.
- [ ] SDK-backed paths have no-real-key fake runner coverage.
- [ ] API/SSE contracts for learning, notes, reviews, plans, and dashboard/resume remain compatible.
- [ ] No hidden tests, reference answers, raw provider errors, raw SDK events, or secrets leak in public responses.
- [ ] Documentation/spec updates capture stable SDK ownership rules and fallback behavior.
- [ ] Release readiness report states whether application-on-SDK is ready for local MVP use.

## Out Of Scope

- New Agent product features.
- Real model quality benchmarking beyond documented optional smoke.
- Frontend redesign.
- Production deployment.
- Replacing deterministic runner/evaluation/FSRS with SDK logic.

## Dependencies

This task should run after:

1. `05-23-sdk-teaching-tools-guardrails`
2. `05-23-sdk-exercise-coach-endpoints`
3. `05-23-sdk-note-assist-agent`
4. `05-23-sdk-review-coach-agent`
5. `05-23-sdk-onboarding-plan-agent`
