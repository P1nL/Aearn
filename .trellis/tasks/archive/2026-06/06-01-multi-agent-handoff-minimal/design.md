# Multi-Agent Handoff Minimal Design

## Router Inputs

`route_message()` remains rule-based and accepts optional context:

- `latest_attempt`
- `learner_profile_summary`
- `tool_context`

Existing callers can omit all optional context and keep the current behavior.

## Routing Rules

- Review sessions always route to `review_coach`.
- Diagnosis stages still route to `diagnosis`.
- Practice stage with repeated/runtime errors routes to `diagnosis` for misconception/error analysis.
- Explicit practice/code requests route to `exercise_coach` when an exercise/tool context is available.
- Repeated-confusion wording plus a profile summary with weak points or error patterns routes to `diagnosis`.
- Existing teaching-stage and practice-stage keyword behavior remains the fallback.

## Handoff Scope

Static handoff target maps stay in place. This task improves initial route selection and prompt handoff context without introducing new agent types.

## Rollback

Remove optional signal handling from the router call; the old stage/keyword rules remain.
