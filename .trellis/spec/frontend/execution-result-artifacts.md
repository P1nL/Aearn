# Execution Result Artifact Presentation

## 1. Scope / Trigger

Apply this contract when changing `TutorArtifactAttemptDetail`, `SafeExecutionResultV2`, `ExecutionResultArtifact`, Attempt-detail loading/cache behavior, result table/output presentation, or “return to edit” in the Tutor conversation timeline.

## 2. Signatures

```ts
fetchTutorArtifactAttempt({
  userId, conversationId, artifactId, artifactVersion,
  learningTrackId, knowledgeKey, teachingSessionId, attemptId,
}): Promise<TutorArtifactAttemptDetail>

<ExecutionResultArtifact
  artifact={artifact}
  loadAttempt={loadAttempt}
  onReturnToSource={returnToSource}
/>
```

The Desktop accepts historical `tutor_learning_artifact_attempt_v1` and strict `tutor_learning_artifact_attempt_v2`. Only v2 exposes typed `execution_result`; the renderer never inspects arbitrary v1 `safe_feedback`.

## 3. Contracts

- Parse Attempt/result/location/table payloads from `unknown` with exact keys, enums, counts, hashes, scope identity, hidden ordinals, protected-content checks, Unicode-code-point string bounds, JSON-safe numeric bounds, and the same UTF-8 table payload bound as the backend.
- Cache one Attempt-detail promise by `conversation + Artifact ID + Artifact version + Attempt ID`. A rejected/mismatched request is removed from cache so an explicit retry can reload authority.
- Render failures before the aggregate passed count. Never render a hidden case ID; hidden failure copy must already be the fixed server-safe message.
- Show only nonempty stdout/stderr in native disclosures. Never show the internal diagnostic code, path, stack, command, runtime/container identity, or provider details.
- Render `table_result_v1` inside a focusable bounded horizontal scroll region. Cells are public scalar values only; `null` renders as `NULL`.
- Passed results show one concise all-passed overview and no redundant “other N passed” line. Failed results may show `其他 N 项通过` after the failures.
- Result instruction/terminal summary is rendered once. The dedicated terminal result renderer owns the detailed body; the shared Artifact shell must not duplicate identical summary Markdown.
- A failed result may expose “返回修改” only when there is exactly one source Artifact reference with a positive exact source version. `content_hash` is optional for an Artifact-version reference. The callback scrolls reduced-motion-aware and focuses the existing source toggle without creating navigation or learning authority.
- Desktop does not expose Submit after Run, derive pass/score, merge historical Runs, execute code, or create Tutor evaluation text.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Attempt scope/version/ID differs from the result Artifact | `ARTIFACT_ATTEMPT_CONTRACT_ERROR`; no partial detail |
| v1 historical Attempt | show the historical-result notice; do not inspect `safe_feedback` |
| v2 result has unknown/extra/protected or out-of-bound data | reject the entire Attempt payload |
| Terminal result has no runtime detail | show the authoritative no-runtime-detail state |
| Empty stdout/stderr | omit its disclosure completely |
| Source reference is missing/ambiguous/versionless | disable/deny return and show a stable stale-source error |
| Exact source is present | one scroll and focus transfer; preserve one Tutor timeline/SSE reducer |
| 1440x900, 900x900, or 390x844 page overflow | fail the browser gate |

## 5. Good / Base / Bad Cases

- **Good:** A failed v2 result shows visible and generic non-visible failures, numeric locations, one passed aggregate, optional output, a bounded table, and a source-return action.
- **Good:** A passed result shows `全部通过` and `N/N 项通过` once, with no Submit, return action, empty output disclosure, or diagnostic label.
- **Base:** A v1 result remains readable as historical evidence without trying to render untyped feedback.
- **Bad:** Rendering `diagnostic_code`, hidden case IDs, raw `safe_feedback`, or a second locally calculated score.
- **Bad:** Requiring an Artifact source `content_hash` when exact Artifact ID/version is the available provenance contract.

## 6. Tests Required

- API-boundary Vitest for v1/v2 exact parsing, location/table bounds, protected values, scope/version mismatch, and unknown/extra fields.
- Component Vitest for failure ordering, hidden ID omission, concise passed state, output disclosures, table scroll/focus, result-summary non-duplication, and no Submit.
- Conversation-surface test for exact Attempt loading and source return without requiring a content hash.
- Full Desktop Vitest and approved `desktop:check`.
- Real browser fixture at 1440x900, 900x900, and 390x844 plus reduced motion: load result detail, open outputs/table, return to source, assert focus, one timeline/Composer, no overflow/overlay/protected marker, and zero relevant console warnings/errors.

## 7. Wrong vs Correct

### Wrong

```tsx
<pre>{JSON.stringify(attempt.result.safe_feedback, null, 2)}</pre>
<p>诊断：{attempt.result.execution_result.diagnostic_code}</p>
```

### Correct

```tsx
const failures = result.test_feedback.filter((item) => !item.passed);
return <ExecutionResultArtifact
  artifact={artifact}
  loadAttempt={loadExactAttempt}
  onReturnToSource={focusVersionedSourceArtifact}
/>;
```

The correct renderer consumes only the strict public contract and owns display/focus state, never execution or learning authority.
