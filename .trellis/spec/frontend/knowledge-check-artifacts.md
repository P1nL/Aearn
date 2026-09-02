# Knowledge Check Artifact Interaction

## 1. Scope / Trigger

Apply when rendering `knowledge_check_v1`, collecting structured responses,
opening Hint overlays, showing direct-answer controls, or changing responsive and
keyboard behavior for conversation-native checks.

## 2. Signatures

```ts
type KnowledgeResponse =
  | { kind: "single_select"; value: string }
  | { kind: "multi_select"; values: string[] }
  | { kind: "prediction" | "short_text"; text: string }
  | { kind: "ordering"; values: string[] }
  | { kind: "code_range"; start_line: number; end_line: number; category: string; note: string };
```

The renderer owns `request_hint`, `request_direct_answer`, and `respond`; the
generic Artifact shell must not duplicate these controls.

## 3. Contracts

- Render only the strict server presentation and base `D(n)`. Never score,
  disclose answers, select successors, or infer mastery locally.
- Disable submit until the response shape is complete. Ordering controls preserve
  every option exactly once; code-range controls enforce positive ordered lines.
- After a successful terminal action, render the server outcome/evaluation and
  keep the original response controls read-only.
- Hint content is a body portal/fixed overlay so opening and paging do not change
  Artifact or conversation height. Pages move only after explicit learner action.
- Escape and the close button close the overlay and restore the exact trigger
  focus. ArrowLeft/ArrowRight/Home/End page only among unlocked Hints.
- Off-screen pages use both `aria-hidden` and `inert`, preventing links or other
  Markdown descendants from receiving keyboard focus.
- Narrow layout uses a bounded bottom sheet; desktop uses an anchored bounded
  popover. Both contain their own scrolling and cannot create page-level overflow.
- Reduced motion removes the horizontal transition without changing page state or
  assistance receipt behavior.

## 4. Validation & Error Matrix

| Condition | UI behavior |
| --- | --- |
| Unknown/extra presentation or response kind | visible contract error; no action |
| Busy or missing action handler | controls disabled |
| Answer locked | no editable response or new-Hint control |
| Hidden Hint page | `aria-hidden` and `inert` |
| Escape | close and restore trigger focus |
| Reduced motion | immediate page change; no auto-advance |

## 5. Good / Base / Bad Cases

- **Good:** The learner opens H1, explicitly unlocks H2, returns to H1, closes,
  reopens, and no extra receipt is inferred by local navigation.
- **Base:** A completed check remains expanded with the authoritative evaluation.
- **Bad:** Rendering Hint pages inline, auto-advancing them, or leaving off-screen
  Markdown links tabbable.

## 6. Tests Required

- Vitest covers every response editor, disabled/busy state, immutable completion,
  direct-answer action, manual Hint unlock/paging, Escape, focus return, inert
  pages, and reduced-motion source guard.
- Full Desktop Vitest and `desktop:check` must pass.
- Final browser evidence covers 1440x900, 900x900, and 390x844 with no reflow,
  clipping, page overflow, focus loss, or console warning/error.

## 7. Wrong vs Correct

### Wrong

```tsx
<div className="hint-inline">{allHints}</div>
```

### Correct

```tsx
createPortal(
  <div className="knowledge-check-hint-layer">
    <section role="dialog">{unlockedPages}</section>
  </div>,
  document.body,
)
```

The overlay is presentation only; the server remains the assistance authority.
