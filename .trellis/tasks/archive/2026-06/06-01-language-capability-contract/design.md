# Language Capability Contract Design

## Purpose

The contract is the gate between product language promises and actual Aearn capabilities. It should let services, graph runtime, runner selection, RAG retrieval, agents, tests, and desktop UI ask one question: "What can Aearn safely do for this language right now?"

## Contract Shape

Introduce a typed capability record in the backend implementation task. The exact file can be chosen during implementation, but the record should be service-owned and testable without importing route handlers.

Proposed logical fields:

```text
LanguageCapability
- language_id: public product language id
- display_name: user-facing language name
- aliases: normalized user input aliases
- current_public_course_language: existing course enum value or null
- capability_state: full | partial | planned | unsupported
- lesson_generation: full | partial | planned | unsupported
- grounding: official | trusted | internal_only | planned | unsupported
- exercise_generation: executable | static_review | planned | unsupported
- execution: browser_preview | python_stdout_test | sql_later | node_later | compiled_later | none
- tests: visible_hidden | visible_only | static_review_only | none
- static_analysis: syntax_only | lint_later | planned | none
- review_feedback: full | static_only | planned | unsupported
- presentation: browser_preview | stdout | citation_only | static_feedback | none
- ux_disclosure: short product-safe copy
- runner_key: browser | python | sql | node | compiled | none
- source_trust_policy: official | trusted_de_facto | internal
- enabled_for_public_selection: boolean
```

The implementation may use Pydantic models, dataclasses, or literal dictionaries, but tests must lock the public values and prevent capability drift.

## Current-State Matrix

| Language | Current public model | Lesson | Grounding target | Exercise | Execution | Tests | Review feedback | UX disclosure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Python | `python` | Supported | Official docs planned | Executable exercises | `python_stdout_test` via existing subprocess sandbox | Visible/hidden style test results | Full feedback from run results and static review | Can run Python stdout/tests; not OS-container isolation |
| JavaScript | `javascript` | Supported | MDN planned | Browser/DOM exercises | `browser_preview` | DOM/preview assertions | Full feedback from preview/test inspection | Can preview browser interactions |
| TypeScript | Not public yet | Planned | Official/trusted docs planned | Static or Node/TS later | `node_later` | Planned | Static review planned | Not runnable until Node/TS runner exists |
| Java | `java` placeholder | Partial | Official docs planned | Static reading/review | `compiled_later` | None now | Static review only | Compile/run sandbox planned later |
| Go | Not public yet | Planned | Official docs planned | Static or compiled later | `compiled_later` | Planned | Static review planned | Not runnable until compiled runner exists |
| C# | Not public yet | Planned | Official docs planned | Static or compiled later | `compiled_later` | Planned | Static review planned | Not runnable until compiled runner exists |
| Rust | Not public yet | Planned | Official docs planned | Static or compiled later | `compiled_later` | Planned | Static review planned | Not runnable until compiled runner exists |
| C++ | `cpp` placeholder | Partial | Trusted/de facto docs planned | Static reading/review | `compiled_later` | None now | Static review only | Compile/run sandbox planned later; cppreference may be trusted/de facto |
| SQL | Not public yet | Planned | Official/vendor-neutral trusted docs planned | Query-reading or SQL runner later | `sql_later` | Planned | Static/query feedback planned | Not runnable until SQL runner exists |
| HTML | Part of `html_css` | Supported through combined course | MDN planned | Browser preview exercises | `browser_preview` through `html_css` | Preview assertions | Full visual/static feedback | Runs only through combined HTML/CSS browser preview |
| CSS | Part of `html_css` | Supported through combined course | MDN planned | Browser preview exercises | `browser_preview` through `html_css` | Preview assertions | Full visual/static feedback | Runs only through combined HTML/CSS browser preview |

## Boundaries

- The contract does not execute code. It only describes capability and maps languages to runner categories.
- The runner registry task will consume this contract to select executable runners or unsupported fallbacks.
- The grounding source registry will consume this contract to validate source coverage and trust tier per language.
- The learning graph runtime will consume this contract as context so agent decisions cannot claim unavailable execution.
- Services and repositories remain the durable write boundary. Graph nodes and capability helpers should not write `LearningPlan`, `LearningSession`, `Attempt`, or `ReviewState` rows directly.
- Frontend uses the resulting API metadata to disable or explain run/submit/preview actions; it should not infer capabilities from language names.

## Alignment Rules

When a language becomes public, the same implementation slice must update:

- Pydantic `Language` or replacement model.
- Database `CHECK` constraints for language-bearing tables.
- Seed catalog runtime profiles and courses.
- Course templates and source attribution.
- API examples and docs.
- Desktop type unions and UX disclosure copy.
- Tests proving the API, runtime boundary, and UI affordance all agree.

## Non-Goals

- No runtime web search from agents.
- No claim that Python subprocess isolation is equivalent to Docker, Firecracker, or OS-level sandboxing.
- No compiled-language execution until a safe compiled runner exists.
- No separate public `html` or `css` course migration in this planning task.
