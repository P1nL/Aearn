# Learning Agent Integration and QA Contract

## Scenario: Final Cross-Layer Learning-Agent Integration

### 1. Scope / Trigger

- Trigger: changing the LearningTrack/Lesson/Gate/Review end-to-end path, public execution-tier claims, Tutor cutover inventory, language capability matrix, or release-readiness evidence.
- This is a cross-layer PostgreSQL, service, API, Desktop, migration, privacy, and documentation contract.

### 2. Signatures

```text
Core language matrix: python | javascript | typescript | sql
Extension validation: java | html_css
Partial local only: go | csharp
Planned/degraded: rust -> unavailable, cpp -> static_only
Public runtime approval: runtime catalog + reviewed image lock + compatible executor health
Cutover schema identity: all tutor_* tables = target user-owned tables ∪ shared allowlist
```

```python
ExerciseGateService(
    conn,
    composition=ExecutionComposition.PUBLIC | DEVELOPMENT,
    local_runner_available=bool,
    local_runner=optional_runner,
)

ReviewService(...same execution-tier inputs...)
```

### 3. Contracts

- The core matrix must use real PostgreSQL and existing repositories/services to cover track/plan, source-backed Lesson, active assignment, Gate, terminal feedback, private persistence, mastery/progress, review schedule, finite ReviewSession, and review evidence.
- Test orchestration must not reimplement score, unlock, schedule, tier, or finalization authority.
- Review candidate SQL must apply current user/track/knowledge publication scope before `ORDER BY ... LIMIT`; post-limit filtering can let another user's `registered_author` candidates starve valid curated candidates. Service-side rechecking remains defense in depth.
- Empty or missing reviewed image locks keep every public execution-required exercise unavailable. A local injected runner is `teaching_local` only and cannot create `container_verified`, executor health, or image-lock evidence.
- Java and HTML/CSS are extension evidence, not part of the four-language core pass. Go/C# are partial and toolchain-dependent. Rust is not publicly selectable/executable; C++ is static teaching only.
- Every schema `tutor_*` table must be explicitly classified as user-owned cutover target state or a shared immutable/catalog table. The sets must be disjoint and exhaustive.
- Legacy `learning_*`, user-level Tutor plans, review/note rows, and old checkpoints are inventory/deletion inputs only; never silently convert them into LearningTrack evidence.
- Public projections and release evidence omit full submissions, hidden tests, private rubrics/reference answers, provider bodies/reasoning, commands, paths, containers, and secrets.
- Final local readiness is not provider approval, image approval, deployment authorization, or release approval.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Public execution-required Gate has no reviewed lock or compatible health | `execution_tier=unavailable`, `allowed_actions=[]`, no host fallback/job |
| Development fixture has an injected local runner | `execution_tier=teaching_local`; disclosure remains development-only |
| Future `tutor_*` table is absent from both cutover sets | schema reconciliation test fails |
| Table appears in target and shared sets | reconciliation test fails |
| Core language path omits Gate or Review evidence | parameterized integration test fails |
| Stale track/progress/assignment/Gate/session version | existing service conflict; no second authority or projection |
| Protected public/export key appears | privacy assertion fails; do not weaken to substring matching of valid enum values |
| Real provider/Docker smoke not run | record `not executed`; never infer pass |

### 5. Good / Base / Bad Cases

- Good: Python creates one Gate evidence, one review evidence, and one schedule-finalization event while public execution is unavailable and the injected local fixture is `teaching_local`.
- Good: a new user-owned Tutor table is added together with a scoped count query and reconciliation test update.
- Base: a shared immutable exercise version is present without learner rows; cutover remains based on user-owned target state.
- Bad: treating a runtime-catalog entry, Dockerfile, local JDK, or green runner unit test as a reviewed public container lock.
- Bad: checking only root tables and assuming all future descendants are covered without an exhaustive schema test.
- Bad: exporting submission content or writing exact local credentials/paths into readiness evidence.

### 6. Tests Required

- `tests/test_learning_agent_integration_matrix.py`: four core parameterized flows, public/local tier assertions, safe projection audit, extension/degraded capability matrix.
- `tests/test_harness_cutover.py::test_cutover_inventory_explicitly_classifies_every_tutor_table`: real PostgreSQL schema reconciliation.
- Full cutover, DB bootstrap, Action Runtime, context eval/facts/references, Gate, model review, ReviewSession, execution-tier, executor lifecycle, export/reset suites.
- API lock, Ruff, Mypy, serial full pytest; executor lock/Ruff/Mypy/full pytest; Desktop build; DB smoke; Trellis validate; `git diff --check`.
- Browser smoke is required when current UI code changes. Documentation/test-only integration work may rely on the previously recorded current-workspace browser proof, but must not claim new UI evidence.

### 7. Wrong vs Correct

#### Wrong

```python
if runtime_id in runtime_catalog:
    return ExecutionTier.CONTAINER_VERIFIED
```

Catalog presence only describes a contract and cannot authorize public execution.

#### Correct

```python
projection = ExecutionTierResolver().resolve(
    language=capability,
    inputs=ExecutionTierInputs(
        composition=ExecutionComposition.PUBLIC,
        local_runner_available=True,
        runtime_registry=registry,
        executor_availability=availability,
    ),
)
assert registry.lock_for(runtime_id) is not None
assert projection.tier is ExecutionTier.CONTAINER_VERIFIED
```

Both a reviewed immutable lock and compatible health are required; otherwise the public projection remains static-only or unavailable according to the exercise contract.

## Scenario: Adaptive Teaching Integration Final Gate（2026-08-23）

### 1. Scope / Trigger
- Trigger: final integration of TeachingSession, domain events, long-context summaries, exact historical references, recovery, privacy, and Desktop role swap.

### 2. Signatures
- Focused gate: Child 4 `implement.md` listed pytest batch + Desktop tests/build.
- Full gate: serial `pytest -q`, Ruff, Mypy, disposable database bootstrap twice, Browser 1440/900/390, Trellis validate, `git diff --check`.

### 3. Contracts
- Deterministic fake provider fixtures assert closed decisions, provider call count, checkpoint lineage, no auto-next, and protected-marker absence.
- Gate/Review/Lesson services remain business owners; teaching adapters consume receipts rather than reimplementing outcomes.
- Browser smoke may use a disposable stateful fake API/provider, but backend Gate/Review evidence must come from real PostgreSQL service/repository tests.
- Bootstrap-heavy PostgreSQL tests are serial; parallel schema bootstrap evidence is invalid.

### 4. Validation & Error Matrix
| Condition | Required result |
| --- | --- |
| focused/full command fails | fix and rerun; do not record partial pass |
| Browser shows overflow/overlay/console warning or protected marker | release gate fails |
| real provider not explicitly authorized | keep `LLM_TYPE=disabled` / injected fake and record non-claim |
| parent acceptance lacks child evidence mapping | do not auto-archive parent |

### 5. Good / Base / Bad Cases
- Good: one disposable Gate completion produces one typed progress event and a validated successor summary; browser role swap preserves draft and has no overflow at all three viewports.
- Base: no frontend code changed; rerun current-workspace browser smoke and record it as regression evidence, not a new feature claim.
- Bad: infer Review/Gate pass from a mock-only UI or call a real provider to make local evidence look stronger.

### 6. Tests Required
- Child 4 focused files plus teaching/Gate/Review/Lesson regression batch.
- Full API, Desktop, bootstrap twice, cutover reconciliation, export/reset/privacy, browser DOM/network/console audit.

### 7. Wrong vs Correct
#### Wrong
`Promise.all([bootstrap_test_a, bootstrap_test_b])` against one shared PostgreSQL schema.
#### Correct
Run one serial pytest process, then create a generated disposable database and execute bootstrap twice before dropping it.
