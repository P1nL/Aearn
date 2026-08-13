# Learner-state proposals

Use this Skill only after selecting this exact reviewed version and only when the current policy explicitly allows the declared effect.

1. `tutor.plan.activate` may create one learner-safe immutable plan revision. Include a short outline, structured diff, learner-safe reason, and stable evidence ids/hashes. The server owns predecessor selection and activation.
2. `tutor.plan.rollback` may move only to the active revision's recorded predecessor. Include learner-safe reason and evidence; never choose another target revision.
3. `tutor.memory.record` may record only an `objective_fact` that is directly supported by bounded learner-safe evidence. Never create an inference, confidence score, retention rule, profile overwrite, or raw conversation storage through this effect.
4. `tutor.activity.record` may record a bounded learner-safe activity item and optional inbox message. Never include raw trace, provider reasoning, prompt, code, URL, path, command, SQL, secret, review, FSRS, attempt, chat, or execution target.

Valid objective-memory action example:

```json
{"type":"propose_effect","effect_type":"tutor.memory.record","payload":[{"key":"memory_kind","value":"objective_fact"},{"key":"category","value":"learning_preference"},{"key":"fact","value":"学习者明确偏好短小且可验证的示例。"},{"key":"evidence_ids","value":["message-42"]},{"key":"evidence_hashes","value":["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]},{"key":"policy_version","value":"tutor_memory_policy_v1"}]}
```

Valid rollback action example; the target revision is intentionally absent because the server chooses the recorded predecessor:

```json
{"type":"propose_effect","effect_type":"tutor.plan.rollback","payload":[{"key":"reason","value":"学习者明确要求撤销最近一次计划调整。"},{"key":"evidence_ids","value":["message-43"]},{"key":"evidence_hashes","value":["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]},{"key":"policy_version","value":"tutor_plan_policy_v1"}]}
```

If an exact effect, evidence, policy, lease, revision, or server-side control is not available, do not propose an effect. Invalid: inferred memory, raw chat, confidence/retention fields, a model-selected rollback revision, or any execution target.
