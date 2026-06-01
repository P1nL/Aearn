# Language capability contract

## Goal

Define the cross-language capability contract that every Aearn learning path uses before expanding public language support. The contract must make lesson generation, RAG grounding, exercise generation, execution, tests, static analysis, review feedback, and UX disclosure explicit per language so the product never promises more capability than the runtime and knowledge layers can provide.

## Confirmed Facts

- Current public backend language enum is `javascript`, `python`, `java`, `cpp`, and `html_css` in `aearn/services/api/app/models/onboarding.py`.
- Current database constraints mirror that enum in `runtime_profiles`, `language_courses`, and `learning_plans`.
- Current seed catalog provides executable-ish support for:
  - `javascript` with `browser_preview` and `runner=browser`.
  - `html_css` with `browser_preview` and `runner=browser`.
  - `python` with `python_stdout_test` and `runner=python`.
  - `java` and `cpp` as `compiled_sandbox_later` placeholders with static reading/review-only exercises.
- Current `runtime_runner.py` has hard-coded branches for `browser_preview`, `python_stdout_test`, and `compiled_sandbox_later`; Python can call the existing subprocess sandbox when real execution is enabled.
- Existing docs already warn that adding TypeScript, Rust, Go, or other public languages requires updating the enum, database checks, course catalog, runtime boundary, API examples, and acceptance tests together.
- This hardening tree targets mainstream language grounding for Python, JavaScript, TypeScript, Java, Go, C#, Rust, C++, SQL, HTML, and CSS, but does not require every language to be executable in the first implementation pass.

## Requirements

- Introduce a single language capability source of truth that downstream code can query instead of scattering language/runtime assumptions across plan generation, runner selection, RAG retrieval, agent prompts, and UI copy.
- Define a capability matrix for Python, JavaScript, TypeScript, Java, Go, C#, Rust, C++, SQL, HTML, and CSS.
- Represent capabilities at least across:
  - lesson generation
  - official/trusted documentation grounding
  - exercise generation
  - code execution
  - visible/hidden tests
  - static analysis or syntax/lint-style validation
  - review feedback and AI patch critique
  - browser preview or stdout result presentation
  - UX disclosure and disabled-action copy
- Distinguish fully supported, partially supported, planned, and unsupported capability states.
- Preserve current behavior for existing public languages while making unsupported or not-yet-executable capability states explicit.
- Make `html` and `css` modeling explicit even if the current runtime still stores the combined `html_css` public course language.
- Define how the contract maps from product language identifiers to existing runtime fields such as `language`, `runtime_tier`, `runner`, and `supported_exercise_types_json`.
- Define how the contract will be consumed by later tasks:
  - runner registry capability lookup
  - source registry and RAG retrieval filters
  - learning graph runtime context
  - exercise generation and review feedback
  - frontend run/submit/preview affordances
- Do not introduce arbitrary runtime web search, Docker/Firecracker sandbox promises, or live execution claims for languages without a safe runner.

## Acceptance Criteria

- [ ] `prd.md`, `design.md`, and `implement.md` describe the language capability contract before implementation starts.
- [ ] The planned capability matrix includes Python, JavaScript, TypeScript, Java, Go, C#, Rust, C++, SQL, HTML, and CSS.
- [ ] Existing current-state mappings are documented for `javascript`, `html_css`, `python`, `java`, and `cpp`.
- [ ] The contract states that Python execution uses the existing subprocess sandbox path and that this is not container-grade isolation.
- [ ] The contract states that unsupported or planned execution returns product-safe capability disclosure instead of pretending to run.
- [ ] The contract defines how to keep Pydantic enums, database checks, seed catalog, API examples, tests, and frontend type unions aligned when a language becomes public.
- [ ] The contract defines at least one testable interface or data shape that later runner, RAG, graph, and frontend tasks can implement against.
- [ ] The contract includes explicit out-of-scope boundaries for this task.

## Out of Scope

- Implementing runner registry code.
- Implementing TypeScript, Node, SQL, compiled-language, Docker, or Firecracker runners.
- Fetching or indexing official documentation.
- Migrating learning page orchestration to the graph runtime.
- Changing public course availability or frontend UI behavior before implementation tasks start.

## Open Questions

- None blocking planning from repository evidence. The main product decision is already implied by the parent task: prefer truthful tiered capability disclosure over broad public support claims.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
