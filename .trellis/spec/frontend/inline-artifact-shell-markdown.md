# Inline Artifact Shell and Safe Markdown

> Conversation-native Artifact rendering and learner-safe Markdown rules for the Aearn Desktop.

## 1. Scope / Trigger

Apply this contract when changing Tutor message Markdown, `TutorPublicArtifactItem` / branch parsing, the inline Artifact shell or registry, Artifact UI-state recovery, clarification-branch rendering, or timeline scroll/focus behavior.

## 2. Signatures

```ts
<SafeMarkdown markdown={text} surface="message | artifact" streaming={boolean} />
<InlineArtifactMessage artifact={artifact} autoReveal={isNewArtifact} terminalCollapseMarker={nextLearnerId} />
<ClarificationBranchGroup conversationId={conversationId} branch={branch}>...</ClarificationBranchGroup>

type TutorConversationSnapshotResponse = {
  snapshot_version:
    | "tutor_conversation_snapshot_v2"
    | "tutor_conversation_snapshot_v3"
    | "tutor_conversation_snapshot_v4"
    | "tutor_conversation_snapshot_v5";
  active_artifact: TutorPublicArtifactItem | null;
  branches: TutorPublicBranchGroup[];
};
```

Custom Markdown directives are exact and closed:

```text
:size[text]{value="sm|md|lg|xl"}
:color[text]{value="#RRGGBB"}
```

## 3. Contracts

- Parse public snapshots, Artifacts, presentations, actions, references, Attempts, and branches from `unknown`; reject extra, unknown, missing, protected, cross-scope, duplicate, stale-identity, bad-hash, and bad-count shapes. Normalize snapshot v2/v3 to `active_artifact=null` and `branches=[]`; v4 adds the Artifact projection and v5 adds exact branch groups.
- Render Markdown through the internal AST only. Never use `dangerouslySetInnerHTML`, `innerHTML`, `DOMParser`, arbitrary CSS, or an HTML fallback. Raw HTML/script/style remains inert visible text. Unclosed fenced code remains one safe code node until closure.
- Allow only fragments or credential-free `http`/`https` URLs with public-looking DNS hostnames; reject relative navigation, protocol-relative URLs, credentials, control characters, backslashes, localhost/`.local`, IP literals, `javascript`, `data`, and other schemes. Color directives require exact six-digit hex and at least 4.5:1 contrast against the declared message or Artifact surface. Invalid/incomplete directives preserve only their learner-visible body unstyled.
- Keep the renderer registry static and exhaustive for the current presentation union. An unknown presentation renders only the contract-error surface and exposes no actions or arbitrary payload content.
- The server owns Artifact state, allowed actions, Attempt/result facts, branch membership, and terminal authority. The Desktop may generate only bounded client action IDs and keep process-local interaction state; it never computes score, pass, mastery, continuation, or branch identity.
- Cache expansion/component/model/scroll/tab state by `conversation_id + artifact_id + version`, carrying the latest UI state forward across authoritative version updates. Reopening the application reloads server detail rather than persisting private/durable Artifact content locally.
- Initial hydration does not identify every existing Artifact as new. A newly added Artifact expands and scrolls to its start once without calling focus; status/version refresh updates the existing shell in place and does not re-scroll. A terminal Artifact stays expanded until the next mainline learner message; branch learner messages never trigger this collapse, and manual reopen survives ordinary refresh.
- Remove exact branch-owned items from the mainline and insert the depth-one group immediately after its anchor Artifact. Active branches remain expanded; resolved branches default to `答疑 · N 轮`, retain manual expansion in process memory, indent only from the left, and preserve the learner bubble right boundary.
- Use container queries, `min-width: 0`, bounded internal scroll regions, 44px interactive targets, visible focus, and reduced-motion behavior. Never add a draggable split, nested Artifact, or a second Tutor timeline/SSE reducer.
- The composer action shelf must reserve its intrinsic height in the normal dock layout, including when controls wrap on narrow screens. Do not translate an absolute shelf over the Artifact timeline or compensate with guessed fixed bottom padding. Verify ordinary scrolling and a real unforced click on Artifact submit controls at 1440x900, 900x900, and 390x844; a jsdom style test alone cannot prove hit-target visibility.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Snapshot v2/v3 | accepted with normalized empty Artifact/branch fields |
| Snapshot v4/v5 Artifact or branch identity mismatch | reject the complete payload; do not partially render |
| Unknown presentation or action | contract error; no arbitrary renderer/action fallback |
| Raw HTML/script/style or unsafe URL | inert text / non-link; no executable DOM seam |
| Invalid or low-contrast directive | body text preserved unstyled; technical syntax hidden |
| SSE/snapshot repeats the same Artifact ID | one shell updated in place |
| Only Artifact status/version changes | no focus or scroll movement |
| Branch learner message follows terminal Artifact | Artifact remains expanded |
| Next mainline learner message follows terminal Artifact | collapse once; manual reopen remains authoritative UI state |
| 1440x900, 900x900, or 390x844 overflow | fail the frontend gate |

## 5. Good / Base / Bad Cases

- Good: a v5 snapshot renders one Artifact, inserts its exact active branch after the anchor, keeps Composer focus, then collapses the resolved branch and terminal Artifact only at their respective authority/UI markers.
- Base: a v2/v3 conversation contains only messages; SafeMarkdown renders ordinary text and the Artifact fields normalize to empty values.
- Bad: cast `response.json()` to the public union, render unknown presentation JSON, infer a branch from adjacency/text, or call `scrollIntoView` on every version refresh.
- Bad: add helper paragraphs such as “component seam” or local explanations that duplicate server title/status/action labels.

## 6. Tests Required

- API-boundary Vitest for snapshot v2-v5, all current presentations, exact Artifact detail/action responses, duplicate/cross-scope/protected/bad-hash shapes, and branch sequence/identity failures.
- Component Vitest for safe AST rendering, inert HTML, URL/color/directive validation, partial fences, copy, registry exhaustiveness, action callback, UI-state carry-forward, new-only scroll, focus preservation, terminal collapse, branch grouping, and source guards.
- `pnpm --dir .\aearn desktop:check` when the approved task explicitly requires it.
- Real browser fixture at 1440x900, 900x900, and 390x844 plus reduced motion: meaningful DOM, one safe interaction, keyboard focus, `scrollWidth <= clientWidth`, no framework overlay, protected-marker/raw-HTML audit, and zero relevant console warning/error.

## 7. Wrong vs Correct

### Wrong

```tsx
<div dangerouslySetInnerHTML={{ __html: artifact.instruction_markdown }} />
```

```ts
if (artifact.state === "completed") localMastery += 1;
```

### Correct

```tsx
<SafeMarkdown markdown={artifact.instruction_markdown} surface="artifact" />
```

```ts
const renderer = artifactRendererFor(artifact.presentation.type);
return renderer ? renderer(props) : <ArtifactContractError />;
```

The renderer projects only validated public authority and owns interaction state, never learning authority.
