# Graph Shared Runtime Contracts

## Goal

Define shared graph runtime contracts so Learning, Onboarding, and Review graph migrations do not each invent their own state, intent, error, and adapter shapes.

## Requirements

- Provide shared types or helpers for graph input state, graph output intents, graph errors, and feature-flag fallback results.
- Keep graph contracts free of direct database connections and repository imports.
- Encode the service/repository persistence boundary: graph outputs request durable actions, services execute them.
- Support safe context only: bounded user text, current-session facts, sanitized summaries, and scoped IDs.
- Prevent leakage of hidden tests, `solution_reference`, full submitted code, raw prompts, provider payloads, stack traces, and secrets.

## Acceptance Criteria

- [ ] Shared contract module exists and is imported by at least one graph migration child.
- [ ] Contract tests cover safe state construction, intent validation, error redaction, and fallback behavior.
- [ ] Contracts represent durable writes as intents, not direct writes.
- [ ] mypy and ruff pass for the shared graph contract layer.
