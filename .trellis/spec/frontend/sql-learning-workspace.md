# SQL Learning Workspace

## 1. Scope / Trigger

Apply this contract when changing the Desktop `sql_workspace_v2` parser, draft/view-state cache, Monaco SQL editor, published Schema tree, copy interaction, explicit Run action, or public table result layout.

The server remains authority for Artifact lifecycle, Attempt status/result, pass/fail, completion, evaluation continuation, and Learning Item publication. Desktop state owns only the in-process draft, editor view state, copy status, and stale-result cue.

## 2. Signatures

```ts
<SqlWorkspaceArtifact artifact={artifact} onAction={actOnArtifact} />

useSqlArtifactDraft(artifact)
updateSqlArtifactQuery(conversationId, artifactId, query)
markSqlArtifactRun(conversationId, artifactId, query)
saveSqlArtifactViewState(conversationId, artifactId, viewState)
```

`sql_workspace_v2` declares `execution_tier="teaching_local"`, SQLite dialect, exact starter/query hashes, 1..8 published tables, at most 32 columns per table, at most 16 foreign keys, and an optional `table_result_v1` bound to one query hash and authoritative Attempt ID.

## 3. Contracts

- Monaco loads lazily and never executes on mount, edit, reconnect, resize, Schema interaction, or authoritative refresh. Only an enabled explicit Run sends the latest complete draft.
- Wide layout is a fixed 50:50 Editor/Schema split. At a Tutor timeline container width of 720px or less, the two panes stack vertically with equal rows. The public result remains one full-width bottom section.
- The Schema tree renders only server-published table/column names, INTEGER/REAL/TEXT types, PK/FK/NULL labels, and FK relations. It never derives or requests hidden datasets, expected rows, rubric, setup SQL, or application database metadata.
- A foreign key must reference exactly one published primary-key column with the same declared type. Unknown tables/columns, nullable PKs, duplicate identities, partial result identity, extra fields, or mismatched active Attempt identity reject the complete Artifact payload.
- Copy controls write only the exact table or qualified column name. Mouse down prevents editor focus transfer; copy never mutates Monaco value/selection, inserts text, opens a completion, or triggers Run.
- Draft and Monaco view state survive authoritative Artifact-version replacement inside the current process. A result is marked stale only after the draft differs from the last explicitly run query; stale is a UI cue, not score authority.
- Pending/running and terminal Artifacts are not runnable; terminal SQL is read-only. Desktop never derives completion from the public grid or hidden-test summary.
- `SafeTableResultGrid` is the single shared table renderer for SQL and terminal execution results. It renders `null` as `NULL`, wraps cells, caps the scroll region, and contains both horizontal and vertical overflow without page overflow.
- Desktop never connects to Aearn PostgreSQL, opens arbitrary database/network targets, parses stdout into a table, or labels local SQLite as container-verified.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Edit without Run | draft/stale UI only; no action request |
| Run while pending, busy, terminal, empty, or action absent | disabled/no-op |
| Schema copy | clipboard gets exact name; editor text, selection, and focus remain unchanged |
| Partial public-result identity or Attempt mismatch | `ARTIFACT_PRESENTATION_CONTRACT_ERROR` at the API boundary |
| Unknown/non-PK/type-mismatched FK | reject the complete payload |
| Large/long table | internal scroll/wrap; no page overflow |
| 1440x900 or 900x900 | equal-width fixed panes |
| 390x844 | equal-height vertical panes and full-width result |
| Reduced motion | no required animated transition for focus or state recovery |

## 5. Good / Base / Bad Cases

- **Good:** The learner edits a query, copies `learners.mentor_id` without losing selection, clicks Run once, receives the public grid, and sees only generic non-visible test feedback through the result Artifact.
- **Base:** A historical `sql_workspace_v1` remains readable through its legacy renderer; no stdout-table inference is added.
- **Bad:** Auto-running on each keystroke, inserting copied names into Monaco, exposing hidden dataset rows, or inferring pass from the visible grid.

## 6. Tests Required

- API-boundary Vitest for exact v2 keys/hashes, nullable PK, FK target/type/identity, result bounds, partial result identity, active Attempt binding, and protected markers.
- Component Vitest for lazy editor behavior, latest-draft explicit Run, no auto-run, copy without value/selection/focus mutation, pending/terminal denial, read-only terminal state, Schema relations, public grid, and NULL formatting.
- Full Desktop Vitest, TypeScript check, and approved Desktop build.
- Real Chromium fixture at 1440x900, 900x900, and 390x844 plus reduced motion. Assert equal wide panes, equal narrow stacked panes, bounded internal result scroll, exact latest submission, no page overflow, and zero relevant console warnings/errors.

## 7. Wrong vs Correct

### Wrong

```tsx
<Editor onChange={(query) => runSql(query)} />
<button onClick={() => editor.insertText(column.name)}>Copy</button>
```

### Correct

```tsx
<Editor value={draft.query} onChange={saveDraftOnly} />
<button onMouseDown={(event) => event.preventDefault()} onClick={() => copyName(qualifiedName)}>复制</button>
<button disabled={!canRun} onClick={runLatestDraft}>运行</button>
```

The correct UI keeps local editing ergonomics separate from the server-authoritative Attempt/result lifecycle.
