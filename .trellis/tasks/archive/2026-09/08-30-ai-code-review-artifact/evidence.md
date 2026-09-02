# Child08 implementation and check evidence

Date: 2026-09-02

## Delivered contracts

- Additive `model_code_review_v2` code/diff presentation and submission while
  preserving historical v1 Artifact and Lesson Gate review contracts.
- Additive immutable `LearningItemModelReviewContentV2` carries exact source and
  modified code authority for published diff reviews. Legacy v1 items continue
  to materialize code-only without migration; the existing Practice/Gate adapter
  receives the modified-code v1 compatibility projection.
- One canonical server builder owns normalized code, source/modified hashes,
  hunk IDs, line keys, complete code-bound line maps, diff hash, and presentation
  hash. The Pydantic contract reconstructs and compares the canonical map, so a
  malformed map remains invalid even when an attacker recomputes its hashes.
- Structured findings require the current presentation hash, one enabled
  hunk/side/category, and a complete contiguous range. Code-only reviews reject
  an invented source side; `uncertain` and other non-correctness verdicts cannot
  carry scored findings.
- Deterministic server scoring covers verdict, discovery/omission, required
  concepts, severity, unsupported findings/false positives, and duplicates.
  Provider/model output does not participate in or mutate the result.
- One immutable private `tutor_model_review_artifact_receipts` row backs each
  completed review. Public Artifact, event, context, Desktop, export, logs, and
  evidence omit full submission, rubric/tests/proofs, expected findings, matcher
  concepts, provider body/reasoning, commands/paths/containers, and secrets.
- Failed review atomically selects one distinct published unused D(n-1)/D(n)
  remediation with smaller scope/lower difficulty; passed review has no
  successor. Missing required remediation rolls back receipt, Artifact, and
  action event. One exact receipt-backed continuation advertises at most the
  persisted successor.
- Active v2 Artifacts must advertise `complete_review`; completed/locked state
  and failed/remediation shape are exact on backend and Desktop boundaries.
- Learning Artifact remains a facade: review v2 creates no second Attempt, Gate,
  Review, mastery, progress, or schedule authority.
- Desktop lazy read-only Monaco code/diff renderer uses complete-hunk selection,
  presentation-owned categories, bounded finding drafts, one renderer-owned
  `complete_review` action, and terminal server-only feedback.
- Schema fragment 190, earlier-fragment compatibility, exhaustive cutover
  inventory, safe export/reset/delete, Trellis backend/frontend specs, and
  current source-of-truth documentation are synchronized.

## Single scoped Trellis check

The one allowed read-only `trellis-check` ran for Child08 and was then closed. It
reported no P0, two P1 findings, and three P2 findings. Main-thread resolutions:

1. **Production diff path unreachable (P1):** added published immutable model
   review content v2 and a real Item Bank -> materializer -> Artifact integration
   test asserting Diff mode, both hashes/maps, and source-side submission.
2. **Self-hashed map not code-bound (P1):** moved canonical map construction into
   the shared contract, require exact canonical equality on backend, and added
   Desktop structural reconstruction against source/modified code, ranges,
   header/counts, keys, and unchanged prefixes/suffixes.
3. **`uncertain + findings` accepted (P2):** backend rejects it; Desktop clears
   findings when switching to uncertain and validates all non-correctness shapes.
4. **Missing action authority (P2):** backend/Desktop parsers require active v2
   `complete_review`; renderer fails closed when called with an unauthorized prop.
5. **Bad-path coverage incomplete (P2):** added scorer penalty matrix, malicious
   rehashed maps, real diff rendering/selection, scope/stale version, append-only
   receipt, no-remediation rollback, export redaction, reset/delete, bootstrap
   twice with an existing receipt, protected field, and missing-action tests.

## Acceptance mapping

| Acceptance criterion | Evidence |
| --- | --- |
| v1 history and old Lesson Gate remain readable | Existing model-review contract/scorer/authoring/repository suites pass beside additive v2 contracts and Desktop registry/API tests. |
| Stable v2 diff mapping and stale identity rejection | Real published diff integration, canonical builder equality, stale hash/unknown hunk/code-source/exact-range tests, and backend/Desktop malicious rehash variants. |
| Repeatable structured finding scoring without exact wording | Repeated equality, reworded concept-token equivalence, wrong verdict, omission, false positive, duplicate, and severity-distance tests. |
| Model evaluation cannot modify result | Server scorer/receipt completes before one exact evaluation continuation; context contains only reason/source/safe summary/successor. |
| Remediation narrows scope/difficulty instead of changing original submission | PostgreSQL failure test preserves immutable original submission and selects a semantically distinct D2 successor for D3; missing successor fully rolls back. |
| Protected rubric/test/proof absent from API/SSE/Desktop | Strict protected-key/marker guards, private receipt projection, serialized Artifact assertions, export redaction, Desktop protected-field rejection, and browser DOM audit. |

## Final automated verification

- Focused serial PostgreSQL/API matrix covering v2 plus existing v1 model review,
  teaching commit/continuation/routes, schema/bootstrap/cutover, Item Bank, and
  Artifact governance: **105 passed in 87.62s**.
- Post-check Action/model-review focused rerun: **33 passed in 14.91s**.
- Complete API suite with `LLM_TYPE=disabled` and `-m "not real_provider"`:
  **856 passed, 2 deselected in 495.41s**.
- API Ruff: **All checks passed**.
- API Mypy: **245 source files, no issues**.
- API compileall and `uv lock --check`: **pass; 55 packages resolved**.
- Desktop full Vitest: **20 files / 143 tests passed**.
- Desktop `tsc && vite build`: **pass, 135 modules transformed**.
- Current docs/spec link/whitespace audit: **10 files checked, 0 errors**.
- `git diff --check`: **pass**; configured LF-to-CRLF warnings only.
- `artifacts/__init__.py` remains contracts-only; fragment 110 still defaults to
  and accepts `tutor_conversation_event_v3` before later fragments.

## Chromium interaction and responsive evidence

A temporary Vite harness outside the worktree mounted the real
`ModelCodeReviewArtifact`, Monaco/DiffEditor, project CSS, one active diff review,
and one terminal code review. It was stopped and removed after the run.

- **1440x900:** document/body `1436 / 1436`; two review surfaces; exactly one
  active completion action; no protected marker.
- **900x900:** document/body `896 / 896`; both reviews `810 / 810`; no page-level
  horizontal overflow.
- **390x844:** document/body `386 / 386`; both reviews and finding editor
  `340 / 340`; Monaco overflow remained internal; no page-level overflow.
- **390x844 reduced motion:** same zero-overflow metrics and exact authority/UI
  state.
- Real interaction: Add Finding -> switch to `uncertain` cleared the finding;
  add again -> enter explanation -> submit produced exact
  `model_code_review_submission_v2` with presentation/hunk/side/range/category.
- Optional `weak_testing` was absent when the presentation exposed only the core
  seven categories. Terminal review exposed zero editable verdict/finding
  controls and only server safe evaluation/remediation text.
- Browser console warnings/errors after the final page load: **0 / 0**.
- Temporary port 1422 was stopped and the temporary harness directory was
  verified absent.

## Non-claims

- No real provider smoke, real executor/container run, or Docker conformance.
- No production image build/sign/publish, Tauri installer, push, deploy, or
  production data migration.
- Deterministic/fake-provider and local Chromium evidence prove repository and UI
  contracts only; they do not prove live model teaching quality or release
  approval.
