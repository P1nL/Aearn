# Learning plan drafting

Use this Skill only for an active `plan_drafting` Tutor run.

1. If language, current experience, goal, weekly time, target level, or teaching preferences are materially missing, answer directly and ask exactly one highest-value follow-up question. Use `wait_for_input` with `continuation_kind=planning_input` and exactly one allowlisted `question_key`; never use `approval` for fact collection.
2. When the information is sufficient, request `learning.plan.draft` once with compact JSON in `profile_json` and contiguous `module_1` through at most `module_8`. Supply a complete replacement plan for revisions, never a partial diff.
3. Use stable lowercase keys for modules, knowledge points, prerequisites, and required capabilities. Keep every compact field within the declared schema.
4. Never provide a URL, source id, path, command, image, runtime target, provider field, hidden rubric, reasoning trace, or effect proposal. Sources and runtime disclosure are server-owned.
5. Treat the returned draft id, version, hash, and quality status as metadata. Tell the learner that the typed plan is ready to review; confirmation remains a separate learner action using `continuation_kind=approval` only when explicit authorization is actually required.

Valid missing-fact action example:

```json
{"type":"wait_for_input","continuation_kind":"planning_input","question_key":"weekly_minutes"}
```

Valid complete-draft action example (compact JSON strings are values, not nested control fields):

```json
{"type":"request_capability","capability_id":"learning.plan.draft","arguments":[{"key":"profile_json","value":"{\"language_id\":\"python\",\"goal_text\":\"掌握基础语法\",\"target_level\":\"beginner\",\"weekly_minutes\":180}"},{"key":"module_1","value":"{\"module_key\":\"python_basics\",\"title\":\"Python 基础\",\"knowledge_keys\":[\"python.variables\"]}"},{"key":"module_2","value":"{\"module_key\":\"python_functions\",\"title\":\"函数\",\"knowledge_keys\":[\"python.functions\"]}"}]}
```

Invalid: `continuation_kind=plan_drafting`, a planning `question_key` paired with `approval`, non-contiguous modules, partial diffs, or model-authored source/runtime claims.
