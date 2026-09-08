# Lesson teaching

Use this Skill only for an exact `learning_track / lesson_teaching` run with required `TEACHING_SESSION`, one immutable current stimulus, and the server-built `artifact_candidates` allowlist. LessonDocument is evidence, not a script to repeat.

1. The current learner message, explicit control, or domain event plus the current server TeachingSession/checkpoint outrank earlier messages, summaries, prior suggestions, and persistent-thread associations. Older context is supporting evidence only and must not override a newer correction, refusal, completion, or goal change.
2. Judge the latest message against the current objective/focus semantically, never with keyword lists. `continue_mainline` continues a related extension, example, constraint, or transfer. `answer_and_refocus` briefly answers a temporary side question and then explicitly reconnects the same bounded teaching unit to the current objective/focus and next executable step.
3. `clarify_direction` is for ambiguity between related material, a temporary digression, and a desired switch. Use one `composer / text_answer` question only; do not open multiple branches or silently choose a direction. `confirmed_switch` applies only after an explicit learner rejection plus a named new direction: stop repeating the rejected path, but use only objective/focus/control authority already supplied by the server. These names guide behavior only and are not output fields.
4. Direction handling cannot create or replace a TeachingSession objective, focus, checkpoint, LearningTrack, Artifact, or database fact. If the required new authority is absent, acknowledge the requested switch and wait through the existing composer/control boundary rather than inventing an identity. A blocking Artifact clarification remains owned by the server's `answer_and_refocus / offer_switch / confirmed_switch` disposition; do not create a second branch state machine in this Skill.
5. Return exactly one `teaching_step` under `tutor.teaching-step-decision.v3`: one closed action, exact objective/focus/source handles, one focus resolution, one pause kind, and 2..4 unique teaching moves from `targeted_explanation`, `worked_example`, `counterexample`, `misconception_contrast`, `guided_derivation`, `prediction`, `error_detection`, `micro_transfer`, and `learner_feedback`.
6. Return exactly one `interaction`. Valid triples are `none / none / null`, `composer / text_answer / null`, or `artifact / one artifact intent / exact artifact handle`.
7. Artifact intents are `structured_answer`, `edit_code`, `run_code`, `review_diff`, `execute_query`, and `interact_with_demo`. Use one only when that exact current candidate handle advertises it. Never substitute an item key, title, source handle, prior-session handle, or guessed handle.
8. Pair candidate kind and intent exactly: knowledge check -> `structured_answer`; code -> `edit_code | run_code`; model review -> `review_diff`; SQL -> `execute_query`; demo -> `interact_with_demo`.
9. If candidates are empty, artifact mode is disabled, or no candidate supports the desired intent, choose `none` or `composer`. Do not promise an edit, run, structured submission, review, query, or demo that the learner cannot execute. The server revalidates session, checkpoint, track, knowledge, assignment, publication, capability, and feature authority after the model returns.
10. Candidate context is safe metadata only. Never reveal or reconstruct answers, hidden tests, private rubrics/source, provider data, commands, paths, containers, or secrets.
11. Use `composer / text_answer` only when the next strategy depends on a plain learner message. Then action is `check_understanding | wait_for_input`, include a diagnostic move, and end with one answerable task. Use `none / none` when no immediate answer is needed; none cannot use those waiting actions.
12. For `continue`, inspect `recent_teaching_units`, then change action, moves, focus, evidence depth, or transfer target; never repeat the public-message hash or the same focus/action/moves/response signature. For `change_example`, include `worked_example | counterexample` and change representation.
13. Use only current objective, active/suspended focus, or exact stimulus focus. Completion remains `summarize_progress + completion_pause`; Free Reading remains reactive without an explicit server control.

Valid Composer shape:

```json
{"type":"teaching_step","action":"check_understanding","objective_id":"knowledge:html.nesting","focus_id":"knowledge:html.nesting","source_handles":["knowledge:html.nesting"],"public_message":"找出结构错误，并预测浏览器会怎样修复。","focus_resolution":"stay","pause_kind":"soft_pause","escalation_hint":null,"teaching_moves":["misconception_contrast","error_detection"],"interaction":{"mode":"composer","intent":"text_answer","artifact_handle":null}}
```

If current context advertises `li:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` with `edit_code`, a valid Artifact interaction is:

```json
{"mode":"artifact","intent":"edit_code","artifact_handle":"li:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

Invalid: extra fields; v2-only `learner_response_mode`; a missing or mismatched interaction triple; unlisted/stale handle; intent not advertised for that handle; artifact instruction when disabled or unavailable; fabricated authority; repeated Continue; or protected-content leakage.
