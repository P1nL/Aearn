# Model Code Review Artifact Interaction

## 1. Scope / Trigger

Apply when parsing or rendering `model_code_review_v2`, lazy-loading Monaco code
or diff views, collecting structured findings, submitting `complete_review`, or
showing the immutable server result/remediation state.

## 2. Signatures

```ts
type ModelReviewFindingV2 = {
  client_finding_id: string;
  hunk_id: string;
  side: "source" | "modified";
  start_line: number;
  end_line: number;
  category: ModelReviewErrorCategoryV2;
  severity: "info" | "low" | "medium" | "high" | "critical";
  explanation: string;
};

<MonacoEditor readOnly />
<MonacoDiffEditor originalEditable={false} readOnly />
```

The dedicated renderer owns `complete_review`; the generic Artifact shell must
not duplicate review controls or terminal evaluation.

## 3. Contracts

- Exact-parse v1 and v2 independently. For v2, recompute normalized code hashes,
  diff identity, full presentation hash, hunk/line ordering, required category
  set, terminal fields, remediation/outcome shape, and Artifact lock state.
- Monaco is lazy, single-file, and read-only. It never runs code, opens files,
  exposes a path/terminal/package manager, or creates learning authority.
- Cursor selection becomes a finding only if every selected line maps to one
  server hunk on the chosen side. A code-only target never emits a source-side
  finding. Invalid selection clears the current selection instead of retaining
  a misleading older range.
- The category selector renders only `review_categories` supplied by the exact
  presentation. The client never invents optional taxonomy entries.
- Local draft state contains only verdict and bounded findings. Submit is
  disabled for an incomplete correctness finding, a non-correctness verdict
  with findings, explanations shorter than eight characters, duplicate client
  IDs, missing action handler, busy state, or terminal lock.
- Submit sends the exact server `presentation_hash`; the frontend does not score,
  inspect private rubric/tests/proofs, choose remediation, infer mastery, or
  synthesize a Tutor evaluation.
- Terminal review stays read-only and renders only server outcome, score, safe
  Markdown evaluation, and a neutral note when a persisted remediation handle
  exists. The full submission and per-finding private match evidence never
  reappear in the DOM.
- Code/diff panes use bounded internal scrolling and responsive stacking without
  page-level horizontal overflow. Controls keep visible focus and usable touch
  targets; reduced motion changes presentation only.

## 4. Validation & Error Matrix

| Condition | UI behavior |
| --- | --- |
| Unknown/extra/protected v2 field or bad hash/hunk/line map | visible Artifact contract error; no action |
| Active Artifact carries locked result or completed Artifact is unlocked | reject the complete Artifact projection |
| Failed result has no remediation, or passed result has one | reject the complete presentation |
| Selection crosses/unmaps a hunk | clear selection; disable Add Finding |
| Presentation omits optional `weak_testing` | do not render that option |
| Busy/missing action handler | disable completion |
| Terminal review | no editable verdict/finding controls |

## 5. Good / Base / Bad Cases

- **Good:** The learner selects modified lines in one diff hunk, adds a closed
  category and explanation, submits once, and sees only the server result.
- **Base:** A code-only review selects the modified side and historical v1 review
  presentation still resolves through its existing renderer.
- **Bad:** Offering every local category regardless of the presentation, keeping
  an old selection after the cursor leaves all hunks, or showing private matcher
  concepts as feedback.

## 6. Tests Required

- API-boundary Vitest with real canonical v2 hashes, active and terminal shapes,
  v1 compatibility, unknown/extra/protected rejection, failed-remediation
  requirement, and Artifact lock-state mismatch.
- Component Vitest for code/diff read-only render, exact payload, category
  filtering, incomplete draft blocking, terminal read-only feedback, and no
  local score/submission replay.
- Full Desktop Vitest and `desktop:check`.
- Final browser evidence at 1440x900, 900x900, and 390x844 covers internal
  scrolling, no page overflow, keyboard/focus, code and diff modes, completed
  state, reduced motion, zero relevant console warnings/errors, and no protected
  marker in DOM.

## 7. Wrong vs Correct

### Wrong

```tsx
<select>{ALL_LOCAL_CATEGORIES}</select>
<button onClick={() => setScore(scoreFindings(findings))}>完成</button>
```

### Correct

```tsx
const categories = KNOWN_CATEGORIES.filter((item) =>
  presentation.review_categories.includes(item.value)
);
await onAction({
  action: "complete_review",
  review_submission: { presentation_hash, verdict, findings },
});
```

The correct renderer limits itself to exact presentation, local draft UX, and
one server-authoritative action.
