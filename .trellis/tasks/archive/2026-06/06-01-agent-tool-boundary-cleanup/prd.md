# Agent tool boundary cleanup

## Goal

Harden agent tools so they emit typed intents while services and repositories own persistence, transactions, and API contracts.

## Confirmed Facts

- `app/agents/graph_runtime_contracts.py` already defines graph-owned typed intents and boundary validation.
- `app/agents/tools.py` currently records write tool side effects in mutable lists, and the service layer decides what to persist.
- Learning conversation persistence already serializes side effects and drains profile updates; agent tools do not open database connections.

## Requirements

- Teach agent write tools to emit typed intents for every durable or externally visible side effect.
- Keep service/repository layers as the only durable write owners.
- Ensure typed tool intents are safe metadata: no raw code, hidden tests, raw prompts, provider payloads, secrets, or stack traces.
- Preserve existing tool return payloads and side-effect lists for compatibility.
- Cover typed intent emission with focused tests.

## Acceptance Criteria

- [ ] Stage update, diagnosis, attempt record, profile update, and code-run tool paths emit typed intents.
- [ ] Attempt intents do not contain raw submitted code.
- [ ] Serialized side-effect metadata can expose bounded typed intents for observability/debugging.
- [ ] Existing learning session tests continue to pass without moving persistence into tools.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
