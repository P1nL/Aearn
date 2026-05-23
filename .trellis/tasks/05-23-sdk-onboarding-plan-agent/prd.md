# Add SDK onboarding plan agent

## Goal

Add SDK-backed onboarding and `plan_draft` generation for Aearn learning goals while preserving deterministic course templates, plan validation, confirm-plan writes, idempotency, and MVP runtime boundaries.

The SDK should help clarify goals and shape a plan draft, but Aearn must still constrain the result to the supported programming-language learning catalog and validated MVP runtime capabilities.

## Requirements

- Add an Aearn-owned SDK Onboarding Plan Agent under `aearn/services/api/app/agents/`, likely `onboarding_plan_agent.py`.
- Preserve existing public contract for:
  - `POST /api/plans/generate`;
  - `POST /api/plans`;
  - `GET /api/plans/{plan_id}`.
- SDK may assist with:
  - clarifying missing learner goal details;
  - selecting relevant modules from existing course/runtime templates;
  - producing `agent_notes`;
  - drafting a validated `PlanDraft` shape.
- Aearn must remain responsible for:
  - course catalog lookup;
  - runtime tier boundaries;
  - `PlanDraft` schema validation;
  - rejecting unsupported or over-broad plans;
  - confirm-plan durable writes;
  - initializing `ReviewState`;
  - idempotency.
- Preserve deterministic fallback to existing plan generation when SDK is unavailable, blocked, or invalid.
- Do not allow SDK to invent unsupported runtime promises, create arbitrary non-programming courses, or bypass `has_supported_mvp_runtime(...)`.

## Acceptance Criteria

- [ ] `app/agents/onboarding_plan_agent.py` or equivalent exists and is used by plan generation.
- [ ] `POST /api/plans/generate` still returns a valid `plan_draft` matching current models and contract.
- [ ] Invalid SDK output is rejected and falls back to deterministic generation.
- [ ] `POST /api/plans` still validates and writes plans in `plan_repository.py`; SDK code does not write `LearningPlan`, `PlanModule`, `KnowledgePoint`, or `ReviewState`.
- [ ] Runtime boundary notices remain accurate for JS/HTML/CSS, Python, Java, and C++.
- [ ] SDK output cannot expand the MVP back into generic subject learning.
- [ ] Existing `tests/test_onboarding_m2.py` still passes.
- [ ] Focused fake SDK tests cover valid draft, invalid draft, unsupported runtime claim, and fallback.

## Out Of Scope

- Dynamic course catalog generation.
- Arbitrary multi-file project curriculum generation.
- Changing database schema for plans or knowledge points.
- Frontend onboarding redesign.
- Real model quality evaluation.

## Dependencies

- This can run after `05-23-sdk-teaching-tools-guardrails`; it should also reuse provider/runtime diagnostics from earlier SDK slices.
- It should execute before final SDK QA release gates.
