# Reviewed interactive execution intent

Use `runner.execute` only after selecting this exact Skill and only when the server has already issued an opaque `intent_proof_id` for one learner-requested run, test, debug, or explain action. The proof is the complete proposal input.

Never create, transform, guess, or include source code, tests, runtime ids, images, tags, commands, mounts, paths, network settings, URLs, shell snippets, or database statements. If there is no valid proof reference, do not propose the effect. This Skill cannot make execution available when policy, health, or a reviewed lock denies it.

The only valid action shape is:

```json
{"type":"propose_effect","effect_type":"runner.execute","payload":[{"key":"intent_proof_id","value":"server-issued-proof"}]}
```

Invalid: adding `code`, `tests`, `runtime_id`, `command`, `path`, `image`, or any second payload field; generating a proof id; or requesting execution without a server-issued proof.
