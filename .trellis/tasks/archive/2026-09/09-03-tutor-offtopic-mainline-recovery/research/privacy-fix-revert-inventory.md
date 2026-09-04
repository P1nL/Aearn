# Research: mistaken raw-reasoning privacy fix revert inventory

- Query: Identify every current working-tree change that belongs only to the retracted raw-reasoning privacy interpretation and must be reverted without disturbing semantic conversation-direction recovery.
- Scope: internal
- Date: 2026-09-04

## Findings

### Correction boundary

The accepted defect is conversation-direction recovery, not a privacy failure. The privacy-only patch is the set of changes that changed Codex Runtime `reasoning`/summary/commentary from an owner-scoped public Runtime stream into `ignored_nonpublic`/final-answer-only behavior, plus its tests and documentation. Revert those hunks only. Keep the semantic direction policy, Codex planning signals, append-only planning-fact reopen behavior, immutable Skill versions, and direction scenario tests.

### Exact semantic revert inventory

The inventory below is hunk-level: revert the named symbols/sections/assertions, not unrelated content in the same file.

#### Task planning artifacts

| File | Privacy-only material to retract | Preserve |
| --- | --- | --- |
| `.trellis/tasks/09-03-tutor-offtopic-mainline-recovery/prd.md` | Background bullet at line 13; R12 at line 28; AC12-AC14 at lines 43-45. | Goal/R1-R11/AC1-AC11 for semantic direction recovery (`prd.md:3-42`). |
| `.trellis/tasks/09-03-tutor-offtopic-mainline-recovery/design.md` | Entire §3.5 “Codex Runtime 原始推理隐私边界” (`design.md:64-74`). | Shared four-way direction model and Codex planning behavior (`design.md:7-63`). |
| `.trellis/tasks/09-03-tutor-offtopic-mainline-recovery/implement.md` | Entire §7 “封闭 Codex 原始思考链公开路径” (`implement.md:54-61`). | Direction implementation/test/spec plan (`implement.md:9-53`, `63-95`). |
| `.trellis/tasks/09-03-tutor-offtopic-mainline-recovery/research/current-behavior.md` | Entire 2026-09-04 privacy supplement (`current-behavior.md:63-80`). | Direction problem, root cause, behavior classes, scenarios and recommendation (`current-behavior.md:3-62`). |

#### Backend runtime/public projection

| File | Privacy-only hunk/symbol |
| --- | --- |
| `aearn/services/api/app/services/tutor/runtime_projection.py` | `TutorRuntimeProjectionStatus.IGNORED_NONPUBLIC` use for reasoning (`runtime_projection.py:44-48`, `767-768`); final-answer-only filters in `runtime_output_for_run`, `runtime_output_for_message`, and `link_completed_text_items_to_message` (`477-522`); `_project_text_item` rejection of non-`final_answer` channels (`552-565`); final-answer-only snapshot payload (`697-715`); non-final phase rejection and final-only stream projection (`767-798`); final-only terminal discard emission (`865-904`). Do not wholesale revert unrelated Runtime fencing, idempotency, safety, or terminal logic. |
| `aearn/services/api/app/services/tutor/conversation_contracts.py` | `TutorRuntimeOutput` reduced to `final_answer_item` only (`conversation_contracts.py:101-113`); Runtime SSE payload channel narrowed to `Literal["final_answer"]` (`296-333`). Restore the prior reasoning-capable closed Runtime contract rather than loosening it to arbitrary channels. |
| `aearn/services/api/app/services/tutor/persistence/conversation.py` | SQL `items.channel = 'final_answer'` filters and final-only `_runtime_output_payload` (`conversation.py:315-383`); public event replay filter that drops Runtime `channel=reasoning` rows (`1072-1089`). Preserve owner/conversation/message/run scopes and state bounds. |
| `aearn/services/api/app/services/tutor/public_api.py` | `_is_public_conversation_event` final-answer-only Runtime allowlist (`public_api.py:2026-2035`). Preserve strict version validation and normal Harness public-thinking filtering. |

#### Desktop Runtime contract/reducer/rendering

| File | Privacy-only hunk/symbol |
| --- | --- |
| `aearn/apps/desktop/src/contracts/tutor.ts` | `TutorRuntimeOutput` final-answer-only shape and Runtime stream `channel: "final_answer"` narrowing (`tutor.ts:775-823`). |
| `aearn/apps/desktop/src/api/tutor.ts` | `toTutorRuntimeOutput` exact keys limited to `final_answer_item` (`tutor.ts:2377-2403` in this file). Restore the prior typed reasoning collection while retaining exact-key validation and length/state bounds. |
| `aearn/apps/desktop/src/hooks/useTutorConversationStream.ts` | `toTutorTurnOutputPayload` rejection of every Runtime channel except `final_answer` (`useTutorConversationStream.ts:258-297`). Restore only the previously supported closed reasoning/final-answer union; do not accept commentary or unknown channels. |
| `aearn/apps/desktop/src/features/tutor/tutorConversationModel.ts` | Reducer/state helpers that retain only `final_answer_item` (`tutorConversationModel.ts:20-87`). Restore reasoning-item reduction/merge independently from final answer. |
| `aearn/apps/desktop/src/features/tutor/TutorConversationParts.tsx` | `TutorRuntimeMessage` and `TutorRunningPlaceholder` final-answer-only rendering and static empty `think` fallback (`TutorConversationParts.tsx:355-388`). Restore the prior Runtime reasoning disclosure behavior without changing Harness `public_thinking_text`. |
| `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx` | Wiring that treats Runtime content as final-answer content only (`TutorConversationSurface.tsx:744-751` plus imported final-only helper at `:36-41`). Preserve fresh-turn identity, snapshot recovery, typed request seat, and queue behavior. |

#### Tests added or rewritten only for the privacy interpretation

| File | Privacy-only assertions/tests to remove or restore |
| --- | --- |
| `aearn/services/api/tests/codex_sidecar/test_codex_runtime_projection.py` | `test_runtime_reasoning_is_receipted_but_never_public_and_final_answer_survives` (`:191-363`); `test_historical_reasoning_rows_and_events_are_filtered_from_public_reads` (`:366-584`); final-answer-only portions of `test_commentary_completion_discards_provisional_final_answer_stream` (`:587-655`). Preserve generic unsafe-message, fence, replay, terminal and final-answer tests. |
| `aearn/services/api/tests/tutor/test_tutor_conversation_runtime.py` | Runtime-event assertion rejecting `channel="reasoning"` (`:76-89`). Preserve the unrelated strict public-item extra-field assertion (`:69-75`). |
| `aearn/apps/desktop/src/tests/tutorApiV2.test.ts` | “accepts final-answer-only Runtime output and rejects reasoning…” (`:472-521`). Preserve item-ID bounds and unrelated snapshot strictness when restoring the reasoning-capable expected shape. |
| `aearn/apps/desktop/src/hooks/tests/useTutorConversationStream.test.ts` | “rejects Runtime reasoning while accepting final-answer item streams” (`:68-128`) and the privacy-gap wording at `:26-31`. Restore positive reasoning-channel coverage and retain rejection of commentary/unknown channels. |
| `aearn/apps/desktop/src/features/tutor/tests/TutorConversationSurface.test.tsx` | “ignores private Runtime reasoning…” (`:764-805`), “does not render injected private Runtime reasoning from history” (`:836-865`), and final-answer-only/empty-think expectations coupled to those tests (`:807-889`). Restore positive live/history reasoning rendering tests while preserving reconnect and final-answer continuity tests. |

#### Product/source-of-truth documentation

| File | Privacy-only section/sentence |
| --- | --- |
| `docs/README.md` | The sentence(s) in the current-state summary declaring Codex raw reasoning/summary/commentary nonpublic end to end (`README.md:19`). Keep the direction-recovery summary in the same paragraph. |
| `docs/product/user-flows.md` | Item 8 “原始推理永不公开” (`user-flows.md:36-39`). Keep item 7 direction recovery (`:32-35`). |
| `docs/setup/codex-sidecar-runtime.md` | Final-answer-only/raw-reasoning filtering clauses in the delta/recovery section (`codex-sidecar-runtime.md:81-85`) and runtime contract bullet (`:111`). |
| `docs/architecture/database-schema.md` | Final-answer-only meaning added to `tutor_runtime_text_items` and body-free-only reasoning receipt/history filtering paragraph (`database-schema.md:468-470`). Preserve table identity, ownership and append-only constraints. |
| `docs/product/frontend-interaction-spec.md` | Entire 2026-09-04 “Codex final answer 与 raw reasoning 隐私边界” section (`frontend-interaction-spec.md:331-337`). |
| `docs/architecture/api-contract.md` | Final-answer-only Runtime output/SSE clauses and reasoning-channel rejection (`api-contract.md:665-675`). Preserve snapshot/SSE versioning and identity rules. |
| `docs/architecture/tutor-harness-runtime.md` | Final-answer-only Runtime projection paragraphs (`tutor-harness-runtime.md:896-900`, `912-916`). Keep semantic direction sections (`:222-244`). |
| `docs/qa/acceptance-test-plan.md` | RT-22 and UX-09 privacy rows plus private-marker fixture paragraph (`acceptance-test-plan.md:410-414`). Keep RT-77-RT-80 direction matrix (`:428-437`). |

#### Trellis specifications

| File | Privacy-only contract to retract |
| --- | --- |
| `.trellis/spec/backend/codex-runtime-sidecar.md` | Nonpublic reasoning/final-answer-only clauses and tests throughout current sections, including `:62-63`, `:97-103`, `:113`, `:358-405`, and `:576-578`. Restore prior owner-scoped reasoning projection language while keeping Runtime sequencing, tool, fencing, thread ownership, and direction contracts. |
| `.trellis/spec/backend/quality-guidelines.md` | Raw-reasoning/final-only acceptance additions near the current end (`quality-guidelines.md:3789-3792`). Do not remove generic provider-secret/protected-field rules elsewhere. |
| `.trellis/spec/frontend/type-safety.md` | Final-answer-only Runtime exact-shape scenario (`type-safety.md:527-548`). |
| `.trellis/spec/frontend/component-guidelines.md` | Final-answer-only/no-reasoning rendering scenario and related bad/test cases (`component-guidelines.md:393-423`), plus privacy-specific bad case at `:276`. |
| `.trellis/spec/frontend/quality-guidelines.md` | Final-answer-only frontend rule (`quality-guidelines.md:390`) and raw-reasoning browser/test criteria (`:901-905`). Preserve the general rule against arbitrary untyped provider payloads. |
| `.trellis/spec/frontend/hook-guidelines.md` | Codex `think` wording changed around owner-scoped Runtime output (`hook-guidelines.md:97-101`) if that hunk was part of the privacy rewrite; restore the previous typed reasoning-stream semantics, not arbitrary provider text. |

### Changes that must not be reverted

- Shared Harness policy in `provider_request.py:23-34`.
- Current immutable Skills and selection: `plan_policy.py:21-27`, `tutor.learning-plan-draft/1.0.3/**`, `tutor.lesson-teaching/1.2.1/**`.
- Codex direction logic/signals in `plan_tools.py:90-109,327-466`, `learning_plan_tools.py:120-246`, and `codex_dispatcher.py:72-81,349-466,635-674`.
- Append-only planning-fact reopening in `planning_facts.py:44-49,152-244`.
- Existing Artifact branch authority in `branch_contracts.py:16-95` and branch persistence/tests.
- Direction-focused tests in `test_tutor_provider_gateway.py:202-286`, `test_codex_learning_plan_tools.py:96-195`, and `test_codex_plan_drafting_cutover.py:437-739`.
- Direction docs/specs in `docs/architecture/tutor-harness-runtime.md:222-244`, `docs/qa/acceptance-test-plan.md:428-437`, and `.trellis/spec/backend/teaching-artifact-orchestration.md:62-78`.

### Files found

The files above are the current semantic privacy patch surface. Modification-time clustering on 2026-09-04 corroborates that the backend projection, Desktop Runtime output, docs/specs, and privacy tests were changed after the 2026-09-03 direction work; modification time is supporting evidence only, not authority.

### External references

- Official OpenAI Codex App Server documentation, `developers.openai.com/codex/app-server`, accessed 2026-09-04: reasoning items and reasoning deltas are first-class App Server notifications, while the client owns how to project them. This does not require Aearn to make them private or public; that is an Aearn product contract decision.
- Local allowed Codex build remains `0.142.0-cometix` (`.trellis/spec/backend/codex-runtime-sidecar.md:43-49`).

### Related specs

- `.trellis/spec/backend/codex-runtime-sidecar.md`
- `.trellis/spec/backend/teaching-artifact-orchestration.md`
- `.trellis/spec/frontend/type-safety.md`
- `.trellis/spec/frontend/component-guidelines.md`
- `.trellis/spec/frontend/hook-guidelines.md`

## Caveats / Not Found

- Researcher role rules prohibit Git operations, so this inventory was produced from current file contents, modification clusters, task artifacts, and semantic markers rather than an executed `git diff`. The main session should run a read-only hunk review before reverting to confirm no parallel edits share the named ranges.
- `implement.jsonl` and `check.jsonl` were intentionally not read because the researcher role is isolated from implement/check manifests.
- Some generic security wording predates the mistaken interpretation. Revert only clauses that make all Codex Runtime reasoning nonpublic/final-answer-only; keep normal strict schemas, owner scope, bounded text, safe logging, secret redaction, and unknown-channel rejection.
