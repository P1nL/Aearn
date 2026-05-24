# Technical Design

## Selected Slice

Only plan-draft generation uses SDK assistance. Durable plan confirmation and review initialization remain in `plan_repository.py`.

## Target Module Shape

```text
aearn/services/api/app/agents/
  sdk_runtime.py
  tools.py
  guardrails.py
  onboarding_plan_agent.py
```

`onboarding_plan_agent.py` should produce a candidate plan draft or structured plan-draft patch from safe user goal and course catalog context.

## Data Flow

1. `routes/plans.py` validates request basics.
2. Aearn loads the user, course, runtime profile, and deterministic template inputs.
3. SDK Onboarding Plan Agent receives safe catalog constraints and user goal text.
4. Candidate output is parsed into current `PlanDraft` models.
5. Aearn validates MVP runtime support and plan shape.
6. If SDK output fails validation, fall back to current deterministic `build_plan_draft(...)`.
7. `POST /api/plans` continues to perform all durable writes.

## Guardrails

The plan agent must block or reject:

- non-programming subject expansion;
- claims that Java/C++ have real compile sandbox support in MVP;
- plans with no runnable JS/HTML/CSS or Python practice path when the selected language should support one;
- direct leakage of provider errors or raw prompts;
- plan drafts that omit required modules or knowledge points.

## Compatibility

The API response should preserve `plan_draft`, `agent_notes`, and runtime boundary fields already used by the frontend. SDK-specific metadata should not leak unless explicitly added to a documented diagnostic field in a later task.

## State Ownership

SDK code must not insert plans, modules, knowledge points, exercises, or review states. It returns candidate structured content only.
