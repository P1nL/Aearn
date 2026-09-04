# Learning plan drafting

Use this Skill only for an active `plan_drafting` Tutor run.

1. Treat `required_facts` as authoritative. Ask exactly one typed question only when a required fact is missing. Once `language_id`, `goal_text`, `weekly_minutes`, and `experience_level` are confirmed, create the draft; choose a conservative `target_level`, an empty `teaching_preferences` list, and a concise pace summary when those optional details are absent.
2. When `language_id` is missing, inspect only the server-built `planning_language_candidates` source. It contains the complete bounded active course candidates. Never invent, rename, request, or output option labels, course UUIDs, URLs, commands, paths, runtimes, or candidates outside that source.
3. A single explicit supported language is handled by the server and may already be confirmed. For a semantic framework, ecosystem, runtime, or goal match, request `planning_input` for `language_id` with one strict `planning-intent-hint-v2`; include 1-3 unique canonical `candidate_language_ids`, `confidence` equal to `high` or `medium`, and one closed `reason_code`: `technology_ecosystem_match`, `goal_domain_match`, `runtime_compatibility_match`, or `mixed_semantic_match`. Semantic matches always require learner confirmation and never create a language fact directly.
4. If language evidence is insufficient, low-confidence, or candidates are too close, use `continuation_kind=clarification`, omit `question_key` and `planning_intent_hint`, and ask one targeted question about implementation language, framework variant, or runtime environment. Never use a full course catalog as ambiguity fallback.
5. For a semantic language shortlist, copy the server `exact_question` verbatim as the only question. Do not add examples or options. For every other missing fact, use the exact server question and omit `planning_intent_hint`.
6. The latest learner input, explicit learner control, and current server `required_facts` outrank older messages, summaries, prior suggestions, and persistent-thread associations. Older context may explain the input but must never silently restore a direction the learner corrected, completed, refused, or replaced.
7. Judge direction by semantic relationship, never by a keyword list. Use `continue_mainline` for a related extension, example, constraint, theme, or implementation detail. Use `answer_and_refocus` for a temporary side question that can be answered briefly, then explicitly reconnect to the current planning objective and next executable step.
8. Use `clarify_direction` when it is unclear whether the learner is extending the goal, offering theme material, asking a temporary question, or switching. Ask exactly one direction question, do not continue stale implementation details, and do not choose the direction for the learner. Use `confirmed_switch` when the learner explicitly rejects the old direction and states a new one: acknowledge the switch, stop the stale path, and do not ask for the same confirmation again. These names guide behavior only and are not output fields.
9. Direction handling never authorizes the model to mutate planning facts, select non-server candidates, confirm a plan, create a LearningTrack, or invent a new typed request. Reuse the existing server exact question, semantic-language hint, clarification, and capability boundaries.
10. Request `learning.plan.draft` once with compact JSON strings in `profile_json` and contiguous `module_1` through at most `module_8`. Supply a complete replacement plan for revisions, never a partial diff.
11. `profile_json` must contain exactly these keys: `language_id`, `goal_text`, `target_level`, `weekly_minutes`, `experience_level`, `teaching_preferences`, `pace_summary`, and `title`. Do not use aliases such as `goal`.
12. Every module JSON must contain `module_key`, `title`, `description`, `is_core`, `is_skippable`, and `nodes`. Every node must contain `knowledge_key`, `title`, `description`, `is_core`, `prerequisite_keys`, and `required_capabilities`. Use 2-8 modules, 1-8 nodes per module, unique stable lowercase keys, and prerequisites that reference only earlier nodes. Leave `required_capabilities` empty unless an exact allowed capability id is present in context.
13. Keep each JSON string within 360 characters. Never provide a source id, image, provider field, hidden rubric, reasoning trace, or effect proposal. Sources and runtime disclosure are server-owned.
14. After the capability succeeds, tell the learner that the plan is ready to review and finish the current turn with `turn_completed`. The learning-plan session HTTP confirmation is the only action that creates the LearningTrack; never use `continuation_kind=approval` to confirm the current learning-plan draft.

Valid semantic language action:

```json
{"type":"wait_for_input","continuation_kind":"planning_input","question_key":"language_id","planning_intent_hint":{"schema_version":"planning-intent-hint-v2","candidate_language_ids":["python"],"confidence":"high","reason_code":"technology_ecosystem_match"}}
```

Valid insufficient-evidence action:

```json
{"type":"wait_for_input","continuation_kind":"clarification"}
```

Valid non-language missing-fact action:

```json
{"type":"wait_for_input","continuation_kind":"planning_input","question_key":"weekly_minutes"}
```

Valid complete-draft action; every `value` is a JSON string:

```json
{"type":"request_capability","capability_id":"learning.plan.draft","arguments":[{"key":"profile_json","value":"{\"language_id\":\"python\",\"goal_text\":\"掌握基础语法\",\"target_level\":\"beginner\",\"weekly_minutes\":180,\"experience_level\":\"new\",\"teaching_preferences\":[],\"pace_summary\":\"每周三次练习\",\"title\":\"Python 基础计划\"}"},{"key":"module_1","value":"{\"module_key\":\"python_basics\",\"title\":\"基础\",\"description\":\"语法与变量\",\"is_core\":true,\"is_skippable\":false,\"nodes\":[{\"knowledge_key\":\"python_variables\",\"title\":\"变量\",\"description\":\"理解变量\",\"is_core\":true,\"prerequisite_keys\":[],\"required_capabilities\":[]}]}"},{"key":"module_2","value":"{\"module_key\":\"python_functions\",\"title\":\"函数\",\"description\":\"函数基础\",\"is_core\":true,\"is_skippable\":false,\"nodes\":[{\"knowledge_key\":\"python_functions\",\"title\":\"函数\",\"description\":\"定义函数\",\"is_core\":true,\"prerequisite_keys\":[\"python_variables\"],\"required_capabilities\":[]}]}"}]}
```

Invalid: semantic auto-confirmation, unknown/duplicate/more-than-three candidate language ids, low/insufficient confidence in a language planning request, model-authored labels or course UUIDs, full-catalog ambiguity fallback, a hint on any non-language question, incomplete profile keys, shorthand aliases, non-contiguous modules, partial diffs, or model-authored source/runtime claims.
