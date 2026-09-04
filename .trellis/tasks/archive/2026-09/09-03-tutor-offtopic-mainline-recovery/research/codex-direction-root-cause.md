# Research: root cause of long Codex deliberation and stale-mainline final behavior

- Query: Explain why Codex can deliberate for too long on a direction-drift input and still finish by asking the old mainline question instead of resolving direction ambiguity.
- Scope: mixed
- Date: 2026-09-04

## Findings

### Files found

- `aearn/services/api/app/services/tutor/codex_dispatcher.py` — persistent-thread setup, long base instructions, primed context, typed-request fallback, and 300-second-class turn timeout.
- `aearn/services/api/app/agents/runtime/learning_plan_tools.py` — six-call/300-second tool budget and transient direction flags.
- `aearn/services/api/app/services/learning/plan_tools.py` — direction flag schema and awaiting-user results.
- `aearn/services/api/app/agents/runtime/contracts.py` — `RuntimeTurnRequest` has only thread/input/tools; no reasoning-effort or direction-phase field.
- `aearn/services/api/app/agents/runtime/codex_adapter.py` — App Server `turn/start` sends only thread ID and input; no `effort` override.
- `aearn/services/api/tests/codex_sidecar/test_codex_plan_drafting_cutover.py` — fake host manually chooses direction flags/final text; tests do not exercise a model that omits the signal.
- `docs/setup/codex-sidecar-runtime.md` and `.trellis/spec/backend/codex-runtime-sidecar.md` — configured 300-second runtime/tool windows and persistent thread contract.

### Root cause 1: the semantic classification is instruction-only at the critical decision point

`_BASE_INSTRUCTIONS` tells Codex to choose among four semantic behaviors (`codex_dispatcher.py:72-81`), but the model-visible tool schema exposes only `clarification_required` and `confirmed_switch`; there is no typed `continue_mainline` or `answer_and_refocus` (`plan_tools.py:90-109`).

This creates an overloaded absence state:

- no direction flag can mean “continue_mainline”; or
- no direction flag can mean “answer_and_refocus”; or
- no direction flag can mean the model failed to notice ambiguity; or
- no direction flag can mean the model ignored the policy and followed the old thread.

The server cannot distinguish those cases.

### Root cause 2: priming makes an old-fact request pending before the model proves direction handling

The dispatcher calls `registry.prime_context()` before starting the model turn (`codex_dispatcher.py:193-200`). If any planning fact is missing, `_awaiting_planning_field(registry)` is already non-null.

During live projection and terminalization, `_codex_typed_request_pending` returns true when a missing field exists even if the model never sent a direction signal (`codex_dispatcher.py:635-640`). Therefore the server is prepared to create the existing next-fact request before it has evidence that the learner’s newest message was semantically reconciled with the old mainline.

This is the immediate authority gap: “a missing fact exists” is treated as sufficient reason to proceed, while “direction ambiguity was resolved” is not a required precondition.

### Root cause 3: the fallback deliberately collapses invalid/missing direction behavior to the old server question

For an ordinary missing fact, `_planning_input_prompt` accepts the model final text only when it:

1. ends with the exact server-owned question; and
2. contains exactly one question mark.

Otherwise it discards the model text and returns only `planning_question_prompt(field)` (`codex_dispatcher.py:643-648`).

That fallback is correct for typed-question authority but wrong as a proof of direction recovery. In the screenshot-like state:

```text
old mainline: website planning
latest learner input: ambiguous new direction (“I want to be a chef”)
primed next missing fact: an old website-plan question
model omits clarification_required
server sees a missing fact and no accepted direction signal
_planning_input_prompt(...) falls back to the exact old question
```

The observable result is exactly the defect: the final Tutor message can be the old mainline question even though the prompt said ambiguity must be resolved first.

### Root cause 4: resolving ambiguity currently requires multiple model/tool phases

The base instructions require every turn to call `aearn_planning_context_read` first (`codex_dispatcher.py:72-78`). The fake host models this as:

1. a context call with only `schema_version` (`test_codex_plan_drafting_cutover.py:255-265`);
2. a second context call with `clarification_required`, `confirmed_switch`, or language hint (`:267-290`);
3. a final natural-language answer (`:292-319`).

The registry also enforces that language candidates must be read before a direction/language resolution call (`learning_plan_tools.py:211-226`). This is safe but increases tool round trips. There is no server fast path that converts a first typed direction decision directly into a bounded server prompt.

### Root cause 5: long reasoning is permitted, not bounded as a direction phase

Current limits are broad plan-drafting limits:

- Codex dispatcher host timeout defaults to 330 seconds and passes `CODEX_RUNTIME_TURN_TIMEOUT_SECONDS + 30` (`codex_dispatcher.py:84-113`, `322-333`).
- The local documented Runtime timeout is 300 seconds (`docs/setup/codex-sidecar-runtime.md:21-26`).
- The dynamic tool registry allows up to 6 calls and 300 seconds (`learning_plan_tools.py:43-64`, `177-181`).
- `RuntimeTurnRequest` has only `thread`, `input`, `tools` (`runtime/contracts.py:122-127`).
- The adapter sends `turn/start` with only `threadId` and `input`, so Aearn does not set a per-turn reasoning `effort` (`codex_adapter.py:148-159`).

Consequently, an intake turn whose only legitimate result is one clarification can consume the same broad deliberation window as a full plan draft.

### Root cause 6: the persistent conversation thread increases stale-direction pressure

A conversation reuses one persistent Codex thread (`codex_dispatcher.py:202-243`). Latest input and server facts are sent as a new turn, while the old thread still contains prior website/implementation associations. The prompt says old context is subordinate (`codex_dispatcher.py:73-75`), but no typed gate prevents those associations from selecting the ordinary next missing fact.

Persistent context is therefore not itself the defect; the defect is that its influence is controlled only by instructions, while the server fallback has a deterministic path back to the stale question.

### Root cause 7: tests encode the desired answer rather than challenge the omission path

Current tests prove:

- the instruction text contains the four names (`test_codex_plan_drafting_cutover.py:397-413`);
- a fake host that explicitly sets `confirmed_switch=True` produces fact reopen (`:516-584`);
- a fake host that supplies answer/refocus-shaped text preserves it (`:645-694`);
- a fake host that explicitly sets `clarification_required=True` persists a clarification (`:697-739`);
- the tool schema can represent clarification/switch (`test_codex_learning_plan_tools.py:96-195`).

They do **not** prove:

- a real model must emit one of four typed dispositions;
- omission is rejected;
- a missing-fact fallback cannot ask the old question after ambiguous input;
- direction resolution completes within a latency/tool-call bound;
- a durable success marker exists.

The fake host manually chooses the successful branch, so the regression cannot expose the production failure mode.

### Why the privacy interpretation was misleading

The raw reasoning stream made the long deliberation visible, but visibility did not cause the deliberation or stale final question. Suppressing the stream changes observation/UI behavior only. It does not alter:

- the missing typed dispositions;
- `_codex_typed_request_pending`;
- the old-question fallback;
- the multi-call protocol;
- the 300-second-class turn/tool budgets;
- the lack of a durable direction receipt.

The actual fix must constrain and verify the decision path, not hide it.

### External references

Official OpenAI Codex App Server documentation (`developers.openai.com/codex/app-server`, accessed 2026-09-04) establishes that:

- `thread/start` accepts `baseInstructions` and `dynamicTools`;
- `turn/start` supports an optional per-turn `effort` override;
- dynamic tool calls are client-executed and return explicit success/content to the model;
- reasoning items/deltas are distinct from final agent-message items.

Aearn currently uses the first two transport surfaces only partially: it sets `baseInstructions`/`dynamicTools` at thread start, but does not send `effort` at turn start (`codex_adapter.py:71-88`, `148-159`). This supports an internal, low-effort bounded intake mode without changing the public API.

### Related specs

- `.trellis/spec/backend/codex-runtime-sidecar.md:171-263` — dynamic planning tools and budgets.
- `docs/architecture/tutor-harness-runtime.md:222-244` — current direction policy and claimed Codex execution.
- `docs/qa/acceptance-test-plan.md:428-437` — current direction matrix; it lacks omission/latency/success-receipt cases.

## Caveats / Not Found

- No real provider turn was executed; the task explicitly excludes real-provider smoke. The latency conclusion is based on configured budgets, request shape, and missing bounds, not a measured provider distribution.
- No explicit reasoning-effort setting was found in Aearn’s Runtime request/config. The provider/Codex default effective effort is therefore external behavior and may vary; the confirmed local fact is that Aearn does not override it.
- The exact screenshot’s first missing field was not available as structured data. The fallback analysis applies to any primed missing field and directly explains why an old mainline question can be emitted.
