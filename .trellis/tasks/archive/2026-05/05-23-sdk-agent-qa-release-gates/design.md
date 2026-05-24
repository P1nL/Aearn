# Technical Design

## Selected Slice

This is a hardening and closeout task, not a new feature slice. It validates all SDK-backed Agent paths together and records stable conventions for future work.

## Verification Matrix

The final matrix should cover these axes:

| Area | Success | Fallback | Guardrail | Contract |
|---|---|---|---|---|
| Teaching messages | fake stream | deterministic | no leakage | JSON/SSE |
| Exercise Coach | fake output | deterministic | no full answer | endpoint JSON |
| Note Assist | fake stream | deterministic | no full rewrite | JSON/SSE |
| Review Coach | fake output | deterministic | no state mutation | review JSON |
| Onboarding Plan | fake structured draft | deterministic | no unsupported runtime claim | plan JSON |

## Test Strategy

Prefer focused tests under existing suites:

- `tests/test_llm_integration.py` for fake SDK and provider/fallback behavior;
- `tests/test_learning_sessions_m3.py` for learning and exercise contracts;
- `tests/test_notes_m5.py` for note assist;
- `tests/test_reviews_m4.py` for review;
- `tests/test_onboarding_m2.py` for plan generation;
- `tests/test_dashboard_resume_m6.py` for resume/review routing compatibility.

Add a shared fake SDK runner only if it reduces duplication and does not hide important per-agent behavior.

## Diagnostics Boundary

Provider diagnostics may include:

- whether model settings are configured;
- normalized base URL host/path without secrets;
- selected model name;
- SDK version if available;
- fallback reason category.

Diagnostics must not include API keys, raw provider responses, stack traces, full prompts, or submitted code.

## Documentation Boundary

Stable implementation rules should be written to `.trellis/spec/backend/quality-guidelines.md` or a more specific backend spec. User-facing product docs should only change if the public behavior or MVP boundary changed.

## Release Report

The release readiness summary should state:

- commands run;
- test results;
- known skipped checks;
- residual risks;
- whether the SDK application layer is ready for local MVP use.
