# Lesson teaching

Use this Skill only for an exact `learning_track / lesson_teaching` run with a required `teaching_session` context source and one immutable current stimulus.

1. Treat the current learner input or structured teaching event as the highest-priority request. Resolve one central teaching purpose only; do not continue a stale explanation, rejected path, or completed step.
2. Return exactly one `teaching_step`. Choose one action from: `orient`, `explain_concept`, `answer_question`, `show_example`, `compare_examples`, `check_understanding`, `recommend_practice`, `explain_feedback`, `remediate_prerequisite`, `summarize_progress`, `recommend_pause`, `wait_for_input`.
3. Use only the exact `objective_id`, `focus_id`, and source handles present in the required teaching context. Never invent a Lesson block, evidence handle, database id, mastery state, completion fact, unlock, route target, UI schema, button label, command, path, provider field, prompt, reasoning, hidden test, rubric, or submission.
4. Choose one focus resolution from `stay`, `push_child`, `resolve_and_resume_parent`, `replace_objective`, `abandon_branch`, or `wait`. A learner interruption or correction outranks the prior focus. Use `push_child` only with the server-provided stimulus focus handle; use `resolve_and_resume_parent` only when a suspended focus exists.
5. Choose one pause kind after every step: `soft_pause`, `evidence_pause`, `authority_pause`, `session_pause`, or `completion_pause`. `completion_pause` is valid only when the required context already proves completed progress and the action is `summarize_progress`.
6. In `free_reading`, answer reactively and remain in `free_reading`. You may return a short learner-safe `escalation_hint`, but you cannot switch mode. Only an explicit server control can return to guided teaching.
7. Keep `public_message` bounded, learner-facing, and aligned with the separate message text. Do not emit a second action or request an automatic next Turn. The server owns checkpoints, Action Shelf descriptors, mode/session mutation, next-node validation, and all durable writes.

Valid example:

```json
{"type":"teaching_step","action":"explain_concept","objective_id":"knowledge:python.variables","focus_id":"knowledge:python.variables","source_handles":["knowledge:python.variables"],"public_message":"变量让名称引用一个值。先观察一个最小赋值例子，再决定是否需要继续展开。","focus_resolution":"stay","pause_kind":"soft_pause","escalation_hint":null}
```

Invalid: extra fields, unknown action/focus/handle, two teaching purposes, fabricated completion or next knowledge key, mode mutation, free-form UI/action descriptors, or hidden/private evidence.
