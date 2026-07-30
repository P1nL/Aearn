# Aearn Historical Runtime Evidence Archive — 2026-07-29

This directory preserves dated source material from the retired Graph/SDK
runtime. These files are evidence and redirect records, **not** active product,
API, dependency, or release contracts. Current readers must start from
[the documentation index](../../README.md) and
[Tutor Harness Runtime](../../architecture/tutor-harness-runtime.md).

| Archived file | Former source path | Reason retained | Current replacement |
| --- | --- | --- | --- |
| `langgraph-state-machine.md` | `docs/architecture/langgraph-state-machine.md` | Historical state-machine/orchestration design evidence | `docs/architecture/tutor-harness-runtime.md` |
| `sdk-agent-release-readiness.md` | `docs/qa/sdk-agent-release-readiness.md` | Historical OpenAI Agents SDK test/release record | `docs/qa/tutor-harness-release-readiness.md` |
| `learning-graph-runtime-demo-story.md` | `docs/qa/learning-graph-runtime-demo-story.md` | Historical learning Graph demo narrative | `docs/product/user-flows.md`, `docs/qa/acceptance-test-plan.md` |
| `agent-capability-hardening-demo-story.md` | `docs/qa/agent-capability-hardening-demo-story.md` | Historical Graph/SDK capability-hardening demo narrative | `docs/architecture/tutor-harness-runtime.md`, `docs/qa/acceptance-test-plan.md` |

Historical terminology, test commands, source paths and present-tense claims in
these documents describe their original delivery state. They must not be copied
into active docs or used to restore a compatibility runtime. Code rollback after
a confirmed clean-slate cutover does not recreate intentionally deleted learner
history.
