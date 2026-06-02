# Local product completion

## Goal

Turn Aearn from a post-MVP engineering slice into a complete local-only desktop learning product. The target is not cloud deployment or SaaS operation; the target is a stable local product that can run, teach, execute supported language exercises, recover from local failures, and explain its own environment/tooling boundaries.

## User Value

- A learner can use Aearn locally as a complete AI programming-language learning app rather than a partial demo.
- The app can guide the learner through route creation, lessons, exercises, review, notes, settings, local environment checks, and safe recovery flows without deployment infrastructure.
- Mainstream language support is honest and capability-gated: supported languages have teaching-grade L3 exercise execution, while unsupported or planned languages do not appear executable.
- Learning answers can be grounded in current lesson material and allowlisted official/trusted documentation, with citations when external documentation is used.
- Local setup failures are diagnosable inside the product through environment checks and Agent-assisted guidance grounded in detected facts.

## Confirmed Decisions

- Deployment is out of scope. The product remains local-only.
- Stable local startup is in scope: API, database, Redis, worker, and desktop should be started or checked through a reliable local entrypoint.
- Local account/data boundaries are in scope: single-machine users, data isolation, reset, export, and deletion.
- Complete learning experience is in scope: route, learning page, exercises, reviews, notes, and settings.
- Language grounding productization is in scope: official/trusted docs should be indexed locally, cited when used, and integrated into learning-agent context without arbitrary live web search.
- Mainstream language expansion targets teaching-grade L3 execution for all selected languages except Rust and C++.
- TypeScript, SQL, Java, Go, and C# must not be presented as executable until their runner contracts are implemented and validated.
- Rust and C++ remain planned/out of scope for L3 execution in this parent task, but their documentation grounding and capability disclosures may exist.
- L3 exercise shapes may differ by language. Aearn is a learning product, not a general online IDE.
- Route A is accepted for runners: detect local native toolchains first; do not bundle every runtime or require container execution by default.
- The product should guide users to install missing language runtimes or configure Docker, but guidance must come from allowlisted static templates. The model can explain detected issues; it must not invent install commands.
- Environment guidance should include both an environment doctor/settings page and Agent-assisted explanations based on detected facts.
- Agent should not automatically install runtimes, rewrite global PATH, or change Docker/WSL/system settings without explicit user confirmation.
- L3 runners support teaching exercises only: single exercise inputs, temporary workspaces, timeouts, bounded stdout/stderr, visible/hidden tests, and stable error categories.
- Full project execution is out of scope for now: no arbitrary npm/Maven/Gradle/Go module/.NET solution support.
- Exercise content should use adaptive templates: fixed knowledge point and scoring contract, dynamic user-specific variants, runner validation before use, and fallback to stable canonical templates.
- Child tasks should be created only when they are about to be planned or implemented. The parent keeps the complete target tree and dependency map.

## Requirements

- Provide a stable local startup/check workflow for the complete Aearn stack.
- Add local product data management: users, learning data isolation, reset/export/delete, and settings-level visibility.
- Fill the desktop product loop across route, learning, exercises, reviews, notes, and settings.
- Productize language grounding: persist allowlisted official/trusted documentation chunks, support deterministic reindex/fixture seed flows, integrate retrieval into learning-agent context, and expose citations/observability safely.
- Expand language capability contracts and runner states so Python, JavaScript, HTML/CSS, TypeScript, SQL, Java, Go, and C# can progress toward teaching-grade L3 support while Rust and C++ remain planned/out of scope for L3.
- Add environment/toolchain detection for Python, Node/TypeScript, browser preview, SQL engine, JDK, Go, .NET, Docker, and database dependencies.
- Add environment guidance templates for Windows-first local setup and Docker configuration, with Agent responses grounded in detected environment facts.
- Implement L3 runner contracts with safe local boundaries: temporary workspace, timeout, bounded output, no network by default, no project-directory writes, stable failure mapping, and hidden-test redaction.
- Add adaptive exercise generation workflow: canonical templates, parameterized variants, model-assisted candidate generation, runner validation, versioning, caching of verified variants, and fallback to stable templates.
- Add Agent quality gates for prompt/graph/router behavior, bad-case regression, capability boundary honesty, grounded citation behavior, and exercise-generation safety.
- Keep existing graph/service/repository ownership boundaries: graph decides actions, services validate and execute, repositories own persistence.

## Complete Child Task Tree

```text
local-product-completion
├─ 01-local-stable-startup
├─ 02-local-user-data-boundary
├─ 03-desktop-learning-experience-completion
├─ 04-language-grounding-productization
│  ├─ grounding-index-persistence
│  ├─ learning-agent-grounding-integration
│  ├─ citation-ux-and-metadata
│  └─ grounding-observability-and-evals
├─ 05-environment-doctor-and-install-guidance
├─ 06-language-l3-runner-contracts
│  ├─ python-runner-hardening
│  ├─ node-typescript-runner
│  ├─ browser-html-css-runner
│  ├─ sql-query-runner
│  └─ managed-compiled-runners-java-go-csharp
├─ 07-adaptive-exercise-template-system
├─ 08-agent-quality-eval-gates
└─ 09-local-product-final-integration-review
```

## Child Task Ownership

- `01-local-stable-startup` owns the reliable local stack entrypoint and checks for API, database, Redis, worker, and desktop.
- `02-local-user-data-boundary` owns single-machine account/data isolation, reset, export, delete, and data-management visibility.
- `03-desktop-learning-experience-completion` owns visible desktop flow completion across route, learning, exercises, reviews, notes, and settings.
- `04-language-grounding-productization` owns official/trusted documentation grounding productization, including persistence, runtime integration, citations, and grounding evals.
- `05-environment-doctor-and-install-guidance` owns toolchain detection, settings visibility, and allowlisted guidance templates for missing local dependencies.
- `06-language-l3-runner-contracts` owns execution capability expansion and stable runner result contracts for supported teaching exercises.
- `07-adaptive-exercise-template-system` owns canonical templates, dynamic variants, runner validation, versioning, and fallback behavior.
- `08-agent-quality-eval-gates` owns prompt/graph/router/eval regression gates across product boundaries.
- `09-local-product-final-integration-review` owns cross-child integration checks and final local-product readiness verdict.

## Dependency Contracts

- `04-language-grounding-productization` depends on the completed language capability matrix and existing `grounding_*` service layer. It must not depend on live arbitrary web search.
- `05-environment-doctor-and-install-guidance` depends on language capabilities and local startup checks. It may use grounding/citation payloads but must rely on allowlisted static install guidance templates.
- `06-language-l3-runner-contracts` depends on language capability and runner registry contracts. Each runner child must write its own missing-toolchain and safety-boundary behavior.
- `07-adaptive-exercise-template-system` depends on at least one stable runner validation path for each target language family it generates exercises for.
- `08-agent-quality-eval-gates` depends on grounding integration, runner contracts, and adaptive exercise contracts being explicit enough to write bad-case regressions.
- `09-local-product-final-integration-review` depends on all selected child tasks being archived or explicitly deferred with a documented reason.

## Phased Delivery

- Phase 1: stabilize local startup, complete core desktop learning loop, productize language grounding, add environment doctor/guidance, and harden Python/JavaScript/HTML/CSS L3 baselines.
- Phase 2: add local user/data management, SQL L3 runner, and adaptive exercise template validation.
- Phase 3: add managed compiled runner support for Java, Go, and C# teaching exercises.
- Phase 4: harden Agent eval gates and complete final local-product integration review.

## Phase 1 Task Order

1. `01-local-stable-startup`
2. `03-desktop-learning-experience-completion`
3. `04-language-grounding-productization`
4. `05-environment-doctor-and-install-guidance`
5. `06-language-l3-runner-contracts/python-runner-hardening`
6. `06-language-l3-runner-contracts/node-typescript-runner`
7. `06-language-l3-runner-contracts/browser-html-css-runner`

## Acceptance Criteria

- [ ] A new local user can start the full stack and complete a learning loop without manual multi-command setup.
- [ ] Local users have isolated route, session, review, note, profile, and settings data.
- [ ] Settings exposes runner/toolchain availability and links to safe install guidance.
- [ ] Agent environment guidance is based on detected facts and allowlisted templates, not free-form invented install commands.
- [ ] Public language cards and Agent responses do not overclaim execution support.
- [ ] Internal lesson RAG is available to the learning agent through a documented, tested context path.
- [ ] Official/trusted documentation grounding is indexed locally and never performs arbitrary live web search during chat.
- [ ] Agent responses include safe citation payloads or citation UI metadata when official/trusted docs grounding is used.
- [ ] L3 runners return stable results for success, compile/syntax error, runtime error, timeout, test failure, unsupported language, and missing toolchain.
- [ ] Hidden tests, solution references, provider payloads, raw prompts, and internal runner details are not exposed to learners.
- [ ] Adaptive exercise variants are validated before use and fall back to stable canonical templates when validation fails.
- [ ] Prompt/graph/router/eval regression gates cover bad cases for direct-answer requests, capability overclaims, missing citations, repeated confusion, runner failures, and dynamic exercise safety.
- [ ] Existing onboarding, learning, review, note, graph, and FSRS flows keep passing their focused regression tests.

## Out of Scope

- Public cloud deployment, SaaS multi-tenancy, payments, production backups, production incident management, and public telemetry.
- Rust and C++ L3 execution.
- General IDE/project execution for arbitrary user repositories.
- Arbitrary third-party package installation inside exercise runners.
- Arbitrary live web search or dynamic documentation crawling during learner chat.
- Automatic runtime installation or global system configuration changes without explicit user approval.

## Open Questions

- None blocking the parent structure. Each child task may introduce child-specific scope questions during its own planning phase.

## Notes

- Keep the parent task in planning until its `prd.md`, `design.md`, and `implement.md` are reviewed.
- Do not start the parent task directly unless it receives direct integration work. Implementation should happen in child tasks.
- Create child tasks incrementally when their planning or implementation begins, not all at once.
