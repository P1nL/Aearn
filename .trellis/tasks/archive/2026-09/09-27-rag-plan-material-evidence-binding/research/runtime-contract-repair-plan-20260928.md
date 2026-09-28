# User-approved runtime/contract repair

User requested repair after clarifying that the failed live run used temporary output/context overrides and that the actual failure was not proven to be prompt wording alone. Continue the existing task, no new task/commit/push/public release.

## Scope

1. Normal real acceptance inherits the project's effective runtime profile. Explicit boundary tests remain separate and auditable; no silent4096/8192/dynamic2048 or acceptance-only thinking override in the normal lane.
2. Preserve complete server-selected Skill executable instructions and capability schemas. No character-clipped JSON or instruction fragment; tight mandatory context fails before model IO, while unrelated user/prose limits remain.
3. Record only safe structural failure facts (allowlisted paths/type/length/count), distinguish union branches correctly, and generate targeted repair guidance. Never echo raw invalid values, silently coerce provider output, weaken business validation, or change published Skill versions.

## Verified local formal baseline

The actual Settings resolver yielded effective context capacity192512, input hard limit131072, output reserve61440, decision max output16384, and dynamic target max130688. See `formal-effective-profile-20260928.json`. The vendor-advertised context setting1000000 is not the effective context budget. Provider/key configuration is separate; no keys are in that file.

## Ownership and gates

- Hypatia (explicit gpt-6-sol/high): D operator formal-profile loading/export/audit and boundary mode, infra-only write scope.
- Dirac (explicit gpt-6-sol/high): protected selected-Skill/schema context delivery and exact integrity/budget tests.
- Pasteur (explicit gpt-6-sol/high): safe typed diagnostics, correct wire/schema validation and planning-specific bounded repair feedback.
- Main: current profile/source-state verification, integration, independent-check dispatch, and any later bounded paid validation.

No worker may make paid API calls or mutate the live database. Existing fifteen live-parent HTTP calls and all prior project events remain recorded, monetary cost unknown. Source capture and admission are already genuine; their current-use authority expires2026-09-28T11:54:38.657105Z. Do not extend old expiry or claim expired material is currently usable. A live validation, if run after offline checks, needs a separately stated bounded call window under the existing project authorization, not renewed user permission. Full-chain success requires real persisted parent, successor, semantic review and exact bindings; offline passes alone do not satisfy it.
