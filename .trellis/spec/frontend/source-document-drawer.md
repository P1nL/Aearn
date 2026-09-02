# Exact Source Document Drawer

## Scenario: Resolve and Display a Frozen LessonDocument Reference

### 1. Scope / Trigger

- Trigger: changing lesson citation clicks, persisted lesson-selection cards, source_inspector_v1, Artifact source chips, the exact reference API, or the right-side document drawer.
- Scope: TrackLearningWorkspace, LessonDocumentView, Tutor timeline cards, Artifact renderers, LessonDocumentDrawer, api/learning.ts, and the Lesson reference resolver.

### 2. Signatures

~~~text
POST /api/learning-tracks/{track_id}/lesson-references/{conversation_id}/resolve
Request source = lesson_block | context_reference | artifact
Response schema = lesson_document_reference_v1
~~~

~~~ts
type LessonDocumentReferenceOpenRequest = {
  knowledgeKey: string;
  source:
    | { kind: "lesson_block"; document_id: string; document_content_hash: string; assignment_version: number; block_id: string; citation_id: string | null }
    | { kind: "context_reference"; reference_id: string }
    | { kind: "artifact"; artifact_id: string; artifact_version: number };
};
~~~

### 3. Contracts

- The server resolves user + conversation + LearningTrack + knowledge scope and returns the exact frozen assignment/document/block/hash. The Desktop never searches text, reuses DOM order, accepts a model selector, or silently switches to the current document.
- A response is accepted only when its scope and source identity match the request. The assignment hash must match the document, target citations must belong to the exact block and source set, and a current reference must carry the same active assignment in current_assignment.
- reference_status=historical renders the requested immutable document plus a visible “内容已更新” notice. It must not highlight a similar block in the active document.
- The drawer is a stable sibling of Tutor/Lesson, not a replacement route or keyed remount. Opening, retargeting, and closing it must preserve Artifact/Monaco/Preview/local draft state.
- Only lesson-document-drawer-scroll scrolls. Target location uses data-document-drawer-block-id after the bounded response renders; a ResizeObserver updates an absolutely positioned highlight without changing block layout.
- Wide/medium layouts use the right-side panel. Below 768px it is a right-aligned min(88vw, 440px) modal overlay; backdrop clicks do not close it. Escape works while the drawer is mounted, and explicit close restores the exact trigger after the close commit.
- Reduced motion uses immediate auto scrolling and a static dashed frame. Source panel heading IDs must be unique when the primary Lesson and drawer coexist.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Unknown/extra request or response field | reject the whole contract; no partial document |
| Cross-user/conversation/track/knowledge source | 404 DOCUMENT_REFERENCE_NOT_FOUND without existence leakage |
| Hash/version/block/excerpt/citation/Artifact version mismatch | 409 DOCUMENT_REFERENCE_STALE; no text fallback |
| Malformed UUID/key/hash/source union | validation or 422 DOCUMENT_REFERENCE_INVALID |
| Exact historical assignment exists | return historical with the frozen document and current assignment pointer |
| Drawer closed by button or Escape | unmount drawer, then restore the stored trigger focus without scrolling the conversation |

### 5. Good / Base / Bad Cases

- Good: a source_inspector_v1 opens its exact Artifact version, scrolls only the document panel to the frozen block, and keeps the editor draft mounted.
- Good: selecting a persisted lesson reference after a migration opens the old document and displays “内容已更新”.
- Base: a Lesson citation without a drawer opener continues to expand the existing LessonSourcesPanel.
- Bad: selecting a lesson block by array index or textContent, or loading the active document when the requested hash is stale.
- Bad: closing on backdrop click, drawing a border on the lesson block itself, or keying Tutor/Lesson by drawer state.

### 6. Tests Required

- Backend PostgreSQL/API: direct block, persisted context reference, source_inspector_v1, malformed/extra input, cross-user/track, stale hash/version, and historical migration.
- Desktop parser: exact keys/source echo, assignment/document/hash/status/citation consistency, and rejection of protected or mismatched payloads.
- Component tests: asynchronous load, retarget, historical notice, internal scroll, absolute highlight, global Escape, narrow focus trap/backdrop behavior, and post-close trigger focus.
- Workspace tests: Tutor/Lesson mount count and local draft state remain unchanged across drawer open/close.
- Real Chromium: 1440x900, 900x900, 390x844, reduced motion, zero page overflow, stable conversation scroll, 88vw narrow drawer, clean console, and no protected markers.

### 7. Wrong vs Correct

#### Wrong

~~~ts
const block = lessonBlocks.find((node) => node.textContent?.includes(reference.excerpt));
block?.scrollIntoView();
~~~

This guesses identity from learner-visible text and may frame the wrong version or change the conversation scroll.

#### Correct

~~~ts
const exact = await fetchLessonDocumentReference({
  userId, trackId, conversationId, knowledgeKey,
  source: { kind: "context_reference", reference_id: referenceId },
});
const block = drawerStage.querySelector(exactBlockSelector(exact.target.block_id));
drawerScroll.scrollTo({ top: block.offsetTop - 18 });
~~~

The server establishes frozen identity; the Desktop only locates that exact block inside the isolated document panel.
