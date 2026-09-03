# Acceptance Matrix: Semantic Planning Language Resolution

| Scenario | Expected authority result | Public request |
| --- | --- | --- |
| Explicit `Python` | deterministic confirmed fact | no language selector |
| Bare LangChain Agent goal + valid model match | no fact until learner responds | Python-only single select, no Java, no default |
| Explicit `LangChain4j` without language word | semantic, not explicit | Java-only single select, no auto-confirm |
| Generic Agent goal, insufficient evidence | no language fact | one text clarification |
| Deterministic frontend direction | existing deterministic intent shortlist | HTML/CSS, JavaScript, TypeScript only |
| Invalid/unknown/stale model candidate | fail closed | never widen to full catalog |
| Feature disabled | explicit legacy rollback | historical full catalog allowed with disabled reason |
| Existing persisted full-catalog request | immutable history | exact old options replay |
| Refresh/reconnect | persisted request authority | same options/order/version |

Security/privacy assertions:

- provider output cannot supply labels, course UUIDs, URLs, commands, paths, runtime config or arbitrary reason text;
- public snapshot omits model confidence and rationale;
- no real provider is required for default acceptance;
- no model semantic result writes confirmed `language_id` without learner response.
