# Learning plan drafting

Use this Skill only for an active `plan_drafting` Tutor run.

1. If language, current experience, goal, weekly time, target level, or teaching preferences are materially missing, answer directly and ask exactly one highest-value follow-up question. Do not call the capability yet.
2. When the information is sufficient, request `learning.plan.draft` once with compact JSON in `profile_json` and contiguous `module_1` through at most `module_8`. Supply a complete replacement plan for revisions, never a partial diff.
3. Use stable lowercase keys for modules, knowledge points, prerequisites, and required capabilities. Keep every compact field within the declared schema.
4. Never provide a URL, source id, path, command, image, runtime target, provider field, hidden rubric, reasoning trace, or effect proposal. Sources and runtime disclosure are server-owned.
5. Treat the returned draft id, version, hash, and quality status as metadata. Tell the learner that the typed plan is ready to review; confirmation remains a separate learner action.
