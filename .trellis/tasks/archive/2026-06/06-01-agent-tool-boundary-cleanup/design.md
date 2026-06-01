# Agent Tool Boundary Cleanup Design

## Boundary

- Agent tools produce return payloads, in-memory side effects, and typed intent metadata.
- Services consume side effects and decide whether to persist, reject, replay, or ignore them.
- Repositories own SQL, transactions, idempotency, and invariant enforcement.

## Intent Mapping

- `update_learning_stage` -> `IntentType.STAGE_UPDATE` target `learning_session`.
- `record_diagnosis` -> `IntentType.SIDE_EFFECT` target `diagnosis`.
- `trigger_code_run` -> `IntentType.TOOL_CALL` target `trigger_code_run`.
- `record_attempt` -> `IntentType.PERSISTENCE` target `attempt`.
- `update_learner_profile` -> `IntentType.PROFILE_UPDATE` target `learner_profile`.

## Safety

- Tool intents use `make_intent()` for redaction and bounding.
- Attempt intent payloads contain only ids, action, and code length; raw learner code stays out of intent metadata.
- Existing side-effect lists stay in place so current service persistence behavior does not regress.

## Compatibility

- Public tool responses remain unchanged.
- `serialize_agent_side_effects()` can include a new `typed_intents` metadata field without changing public API contracts.
