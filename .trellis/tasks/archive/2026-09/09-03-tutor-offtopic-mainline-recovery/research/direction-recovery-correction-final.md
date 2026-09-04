# Research: corrected Codex direction-recovery diagnosis

- Query: Final corrected inventory, root cause, and smallest recommendation after retracting the raw-reasoning privacy interpretation.
- Scope: internal
- Date: 2026-09-04

## Findings

### Revert only the mistaken privacy patch

Revert the privacy-specific hunks that make Codex Runtime reasoning nonpublic/final-answer-only, while preserving every semantic direction-recovery change.

**Task artifacts**
- `prd.md`: remove Background privacy bullet, R12, AC12-AC14; keep R1-R11/AC1-AC11.
- `design.md`: remove §3.5 raw-reasoning privacy section; keep four-way direction model and Codex planning design.
- `implement.md`: remove §7 privacy implementation checklist; keep direction implementation/tests/spec plan.
- `research/current-behavior.md`: remove the 2026-09-04 privacy supplement; keep direction findings.

**Backend privacy-only code**
- `aearn/services/api/app/services/tutor/runtime_projection.py`: revert `ignored_nonpublic` reasoning handling and final-answer-only text/query/payload projection; preserve Runtime fences, safety, idempotency, terminal handling, and Codex direction logic elsewhere.
- `aearn/services/api/app/services/tutor/conversation_contracts.py`: restore the prior closed reasoning-capable Runtime output/SSE union instead of final-answer-only.
- `aearn/services/api/app/services/tutor/persistence/conversation.py`: restore owner-scoped reasoning rows/events in active/history output and replay; preserve scope/state filtering.
- `aearn/services/api/app/services/tutor/public_api.py`: restore reasoning Runtime event publication in `_is_public_conversation_event`; preserve version/shape validation.

**Desktop privacy-only code**
- Restore reasoning-capable typed parsing/reduction/rendering in:
  - `aearn/apps/desktop/src/contracts/tutor.ts`
  - `aearn/apps/desktop/src/api/tutor.ts`
  - `aearn/apps/desktop/src/hooks/useTutorConversationStream.ts`
  - `aearn/apps/desktop/src/features/tutor/tutorConversationModel.ts`
  - `aearn/apps/desktop/src/features/tutor/TutorConversationParts.tsx`
  - `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx`
- Keep exact schemas, bounds, unknown/commentary rejection, snapshot recovery, typed requests, and Harness `public_thinking_text` behavior.

**Privacy-only tests**
- Revert/remove final-answer-only and “reasoning never public” assertions in:
  - `tests/codex_sidecar/test_codex_runtime_projection.py`
  - `tests/tutor/test_tutor_conversation_runtime.py`
  - Desktop `tutorApiV2.test.ts`, `useTutorConversationStream.test.ts`, and `TutorConversationSurface.test.tsx`.
- Restore positive closed reasoning-channel coverage; keep generic unsafe/extra-field/unknown-channel tests.

**Privacy-only docs/specs**
- Retract final-answer-only/raw-reasoning-nonpublic additions in `docs/README.md`, `docs/product/user-flows.md`, `docs/setup/codex-sidecar-runtime.md`, `docs/architecture/{database-schema,api-contract,tutor-harness-runtime}.md`, `docs/product/frontend-interaction-spec.md`, `docs/qa/acceptance-test-plan.md`.
- Retract corresponding clauses in `.trellis/spec/backend/{codex-runtime-sidecar,quality-guidelines}.md` and `.trellis/spec/frontend/{type-safety,component-guidelines,quality-guidelines,hook-guidelines}.md`.
- Do not remove generic secret/provider-payload redaction rules.

### Preserve semantic direction recovery

Keep:
- `provider_request.py` shared `continue_mainline / answer_and_refocus / clarify_direction / confirmed_switch` policy.
- Immutable Skills `tutor.learning-plan-draft@1.0.3` and `tutor.lesson-teaching@1.2.1`, their manifests/evals, and `plan_policy.py` selection.
- `plan_tools.py`/`learning_plan_tools.py` clarification and confirmed-switch signals.
- `codex_dispatcher.py` direction instructions, answer/refocus message preservation, server question authority, and confirmed-switch mapping.
- `planning_facts.py` exact four-field append-only reopen behavior.
- Direction tests and `teaching-artifact-orchestration.md` branch authority.

### Current machine-verifiable coverage

- `continue_mainline`: prompt/Skill semantics only; no typed direction signal or receipt.
- `answer_and_refocus`: prompt semantics plus Codex content-shape check (one question and exact server-question ending); no general direction receipt.
- `clarify_direction`: transient Codex `clarification_required=true` and tool result code; persisted request is only generic `clarification`.
- `confirmed_switch`: transient Codex `confirmed_switch=true`, server fact reopen, then a generic planning/clarification request; no durable direction-resolution receipt.
- Only the blocking Artifact branch has true typed durable dispositions (`answer_and_refocus`, `offer_switch`, `confirmed_switch`).

### Root cause

1. The four-way policy is not a required typed decision. Codex exposes only two optional booleans, so absence ambiguously means valid continuation, answer/refocus, or failure to notice drift.
2. `registry.prime_context()` marks the first missing old-mainline fact before the model proves direction handling.
3. `_codex_typed_request_pending()` treats “a missing fact exists” as enough to create a request even when no direction signal exists.
4. `_planning_input_prompt()` discards nonconforming model text and falls back to the exact old server question. This preserves typed-question authority but reproduces the screenshot defect.
5. Ambiguity currently requires context call -> optional second resolution call -> final answer; no server fast path exists.
6. Intake uses broad limits: up to 6 tool calls and roughly 300 seconds, and Aearn does not send a per-turn App Server `effort` override.
7. Persistent thread context adds stale-direction pressure, while the hard fallback still favors the old missing fact.
8. Tests manually set successful fake-host flags/final text; they do not test omission, latency bound, stale-question suppression, or a durable success marker.

### Smallest server-authoritative recommendation

1. Replace the two optional booleans with one required internal closed `direction_action` candidate on the first model-visible `aearn_planning_context_read` call:
   - `continue_mainline`
   - `answer_and_refocus`
   - `clarify_direction`
   - `confirmed_switch`
2. Treat it as a model candidate only. The server validates current facts/scope and owns all resulting actions:
   - continue -> existing exact question or typed draft;
   - answer/refocus -> learner-safe bounded answer ending with the exact server question;
   - clarify -> one fixed server-owned clarification request;
   - switch -> existing append-only four-field reopen and next server question.
3. Require an accepted direction action before the typed-request path. Missing/invalid/timeout must never fall through to the old fact question; use a fixed server clarification or stable failure.
4. For primed `AWAITING_USER` turns, use a short server-enforced direction deadline, one accepted direction call, no draft call, and low App Server effort when supported. Keep normal effort for complete-fact draft turns.
5. After the mapped action commits, append one server-issued `planning_direction_resolved` event in existing `tutor_run_events` (no migration) with only closed action/result/source, input revision, policy/schema version, facts fingerprint, question key, and server-computed message hash. Persist no model rationale or learner text.
6. Keep the marker internal; no public API/Desktop direction enum and no Artifact branch reuse.

### Exact implementation/test/spec surface

**Runtime/domain**
- `app/services/learning/plan_tools.py`
- `app/agents/runtime/learning_plan_tools.py`
- `app/services/tutor/codex_dispatcher.py`
- `app/agents/runtime/contracts.py`
- `app/agents/runtime/codex_adapter.py`
- `app/services/tutor/persistence/{run.py,_dependencies.py}`
- `app/services/tutor/safe_projection.py`

**Tests**
- `tests/codex_sidecar/test_codex_learning_plan_tools.py`
- `tests/codex_sidecar/test_codex_plan_drafting_cutover.py`
- `tests/codex_sidecar/test_codex_runtime_adapter.py`
- `tests/tutor/test_tutor_run_repository.py`
- `tests/tutor/test_tutor_conversation_runtime.py`

Required cases: all four actions; omitted/invalid/duplicate action; pre-tool delay/timeout; screenshot-like input never asks stale old question; answer/refocus postconditions; exact switch reopen set; idempotent/conflicting receipt; no public snapshot/SSE/Desktop schema change.

**Specs/docs**
- `.trellis/spec/backend/codex-runtime-sidecar.md`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/qa/acceptance-test-plan.md`
- optional concise behavior clarification in `docs/product/user-flows.md`

No new Skill version, database migration, Desktop direction classifier, Runtime projection privacy change, or Artifact branch change is required.

### Risks

- Low effort must apply only to `AWAITING_USER` intake turns or it may harm full plan quality.
- A model can still semantically choose the wrong enum; the server can prove bounded accepted behavior and side effects, not perfect semantic judgment. Real-provider evaluation remains separate.
- The receipt must be server-computed after postconditions; persisting raw model output would recreate model authority.
- Confirmed switch must reopen exactly language/goal/target/experience while preserving weekly time/preferences/pace.
- Privacy and direction edits share docs/task files; revert by named hunks only to protect parallel changes and direction work.

### Files found

Detailed evidence is also persisted in:
- `research/privacy-fix-revert-inventory.md`
- `research/direction-recovery-dataflow.md`
- `research/codex-direction-root-cause.md`
- `research/bounded-direction-authority-design.md`
- `research/affected-files-tests-risks.md`

### External references

Official OpenAI Codex App Server documentation (`developers.openai.com/codex/app-server`, accessed 2026-09-04) documents `baseInstructions`, `dynamicTools`, explicit dynamic-tool responses, and optional `turn/start effort`. The local compatibility target remains Codex `0.142.0-cometix`; effort support should be contract-tested and remain an optimization rather than the authority mechanism.

### Related specs

- `.trellis/spec/backend/codex-runtime-sidecar.md`
- `.trellis/spec/backend/teaching-artifact-orchestration.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`

## Caveats / Not Found

- Researcher role prohibited Git operations, so the revert inventory is semantic hunk-level evidence from current files/task artifacts/modification clusters, not an executed VCS diff. Main session should run one read-only hunk review before reverting.
- `implement.jsonl` and `check.jsonl` were not read because research is role-isolated.
- No real provider turn was executed; latency and fallback causes are established from current control flow and configured bounds, while statistical model quality remains unverified.
