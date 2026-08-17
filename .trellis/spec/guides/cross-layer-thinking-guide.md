# Cross-Layer Thinking Guide

> **Purpose**: Think through data flow across layers before implementing.

---

## The Problem

**Most bugs happen at layer boundaries**, not within layers.

Common cross-layer bugs:
- API returns format A, frontend expects format B
- Database stores X, service transforms to Y, but loses data
- Multiple layers implement the same logic differently

---

## Before Implementing Cross-Layer Features

### Step 1: Map the Data Flow

Draw out how data moves:

```
Source → Transform → Store → Retrieve → Transform → Display
```

For each arrow, ask:
- What format is the data in?
- What could go wrong?
- Who is responsible for validation?

### Step 2: Identify Boundaries

| Boundary | Common Issues |
|----------|---------------|
| API ↔ Service | Type mismatches, missing fields |
| Service ↔ Database | Format conversions, null handling |
| Backend ↔ Frontend | Serialization, date formats |
| Component ↔ Component | Props shape changes |

### Step 3: Define Contracts

For each boundary:
- What is the exact input format?
- What is the exact output format?
- What errors can occur?

---

## Common Cross-Layer Mistakes

### Mistake 1: Implicit Format Assumptions

**Bad**: Assuming date format without checking

**Good**: Explicit format conversion at boundaries

### Mistake 2: Scattered Validation

**Bad**: Validating the same thing in multiple layers

**Good**: Validate once at the entry point

### Mistake 3: Leaky Abstractions

**Bad**: Component knows about database schema

**Good**: Each layer only knows its neighbors

---

## Checklist for Cross-Layer Features

Before implementation:
- [ ] Mapped the complete data flow
- [ ] Identified all layer boundaries
- [ ] Defined format at each boundary
- [ ] Decided where validation happens

After implementation:
- [ ] Tested with edge cases (null, empty, invalid)
- [ ] Verified error handling at each boundary
- [ ] Checked data survives round-trip

---

## Cross-Platform Template Consistency

In Trellis, command templates (e.g., `record-session.md`) exist in **multiple platforms** with identical or near-identical content. This is a cross-layer boundary.

### Checklist: After Modifying Any Command Template

- [ ] Find all platforms with the same command: `find src/templates/*/commands/trellis/ -name "<command>.*"`
- [ ] Update all platform copies (Markdown `.md` and TOML `.toml`)
- [ ] For Gemini TOML: adapt line continuations (`\\` vs `\`) and triple-quoted strings
- [ ] Run `/trellis:check-cross-layer` to verify nothing was missed

**Real-world example**: Updated `record-session.md` in Claude to use `--mode record`, but forgot iFlow, Kilo, OpenCode, and Gemini — caught by cross-layer check.

---

## Generated Runtime Template Upgrade Consistency

Some generated files are both documentation and runtime input. In Trellis,
`.trellis/workflow.md` is parsed by `get_context.py`, `workflow_phase.py`,
SessionStart filters, and per-turn hooks. Template changes must be validated
against both fresh init and upgrade paths.

### Checklist: After Modifying A Runtime-Parsed Template

- [ ] Identify every runtime parser that reads the template, not just the file
  writer that installs it
- [ ] Check whether relevant syntax lives outside obvious managed regions
  such as tag blocks
- [ ] Verify fresh `init` output and a versioned `update` scenario that writes
  the older `.trellis/.version`
- [ ] Add an upgrade regression using an older pristine template fixture, then
  assert the installed file reaches the current packaged shape
- [ ] Update the backend spec that owns the runtime contract

**Real-world example**: Codex inline mode changed workflow platform markers from
`[Codex]` / `[Kilo, Antigravity, Windsurf]` to `[codex-sub-agent]` /
`[codex-inline, Kilo, Antigravity, Windsurf]`. Fresh init was correct, but
`trellis update` only merged `[workflow-state:*]` blocks and preserved stale
markers outside those blocks. Result: upgraded projects got new hook scripts
but old workflow routing, so `get_context.py --mode phase --platform codex`
could return empty Phase 2.1 detail.

---

## Mode-Detection Probe Checklist

When a CLI auto-detects a mode by probing a remote resource (e.g., checking if `index.json` exists to decide marketplace vs direct download):

### Before implementing:
- [ ] Probe runs in **ALL** code paths that use the result (interactive, `-y`, `--flag` combos)
- [ ] 404 vs transient error are distinguished — don't treat both as "not found"
- [ ] Transient errors **abort or retry**, never silently switch modes
- [ ] Shared state (caches, prefetched data) is **reset** when context changes (e.g., user switches source)
- [ ] **Shortcut paths** (e.g., `--template` skipping picker) must have the same error-handling quality as the probed path — check that downstream functions don't call catch-all wrappers

### After implementing:
- [ ] Trace every path from probe result to the mode-decision branch — no fallthrough
- [ ] External format contracts (giget URI, raw URLs) are tested or at least documented as comments
- [ ] Metadata reads consume a complete response or use a streaming parser — never parse a fixed-size prefix as full JSON
- [ ] When reconstructing a composite identifier from parsed parts, verify **all** fields are included and in the **correct position** (e.g., `provider:repo/path#ref` not `provider:repo#ref/path`)
- [ ] Verify that **action functions** called after a shortcut don't internally use the old catch-all fetch — they must use the probe-quality variant when error distinction matters

**Real-world example**: Custom registry flow had 8 bugs across 3 review rounds: (1) probe only ran in interactive mode, (2) transient errors fell through to wrong mode, (3) giget URI had `#ref` in wrong position, (4) prefetched templates leaked across source switches, (5) `--template` shortcut bypassed probe but `downloadTemplateById` internally used catch-all `fetchTemplateIndex`, turning timeouts into "Template not found".

**Real-world example**: Agent-session update hints fetched npm `latest` metadata with `response.read(4096)` and then parsed it as complete JSON. The `@mindfoldhq/trellis` package metadata exceeded 4 KB, so the JSON was truncated, parse failed silently, and the first session injection showed no update hint. Fix: read the complete response before parsing, and add a regression where `version` is followed by an 8 KB metadata tail.

---

## Provisional Stream vs Business Authority

A transport or parser lifecycle milestone is not automatically a product authority milestone.
For streamed model output, name and test the stages explicitly:

```
observed delta -> safely buffered prefix -> parser EOF -> full decision validated -> durable business acceptance
```

Checklist:

- [ ] Which layer owns the final schema/domain/safety decision? That layer must emit the reveal/commit signal.
- [ ] Can a parser or transport report completion before a later validator rejects the object? If yes, do not expose that completion as UI authority.
- [ ] Are provisional events distinguishable from validated events in both naming and consumer behavior?
- [ ] Does the UI keep provisional content off-DOM regardless of elapsed debounce/stability time?
- [ ] Is there a regression where a rejected attempt lasts longer than every frontend timer and still follows `append -> discard` with no `complete`?

**Failure pattern:** a fixed frontend delay hid only fast rejects. Slow invalid Tutor attempts emitted
`append -> complete -> discard` because projector EOF was mistaken for validated decision completion.
The deterministic boundary is to let the gateway emit `complete` only after full decision validation,
then require that authority signal before the frontend reveals its buffered text.

## When to Create Flow Documentation

Create detailed flow docs when:
- Feature spans 3+ layers
- Multiple teams are involved
- Data format is complex
- Feature has caused bugs before

## Integration Catalog and Shared Queue Checklist

When a cross-layer change extends a catalog, adds a target adapter, or reuses a
shared database queue:

- [ ] Resolve a semantic catalog entry by exact stable key/version, never by
  list position or a display label.
- [ ] Classify each module as core Harness or an approved target adapter before
  changing static boundary tests; a narrow data-access allow-list must not
  permit Graph, router, tool, runner, subprocess, or legacy-conversation paths.
- [ ] For shared queue fixture tests, make isolation explicit and trace it
  through seed, claim, and expired-lease recovery; assert another user's rows
  remain untouched.
- [ ] Keep the production worker's global queue semantics explicit. A scoped
  test/maintenance operation must not silently change normal worker behavior.
- [ ] When a shared fixture gains a new non-cascading root receipt or foreign
  key, audit every test that commits fixture rows: cleanup must follow
  child-to-root order and remove only its exact rows, or the next test can
  inherit leaked singleton/queue state.
- [ ] Read language/capability state from the current registry/source of truth,
  not from an older fixture expectation.

## Opaque JSON Action Boundary Checklist

When a model-authored generic `{key,value}` action carries nested JSON as strings:

- [ ] Does the exported machine schema describe every nested key, not only `type=string`?
- [ ] Does the selected exact-versioned Skill repeat the same nested contract and forbid aliases?
- [ ] Did an instruction correction publish a new semantic version instead of rewriting an old bundle?
- [ ] Does one integration test pass an invalid nested object through the real transaction/context-manager boundary?
- [ ] Are custom exceptions at that boundary ordinary mutable exceptions rather than frozen dataclasses?
- [ ] If the action fails after public thinking is visible, does terminal persistence still write one learner-safe formal message?
- [ ] If the final decision creates a typed request, are both the formal Tutor message and composer/approval item persisted atomically and ordered message-first?

**Failure pattern**: hand-authored valid fixtures can prove the domain decoder while missing that the real provider was taught an incomplete nested schema. The resulting domain rejection may then be masked again by exception mechanics, leaving the UI with only intermediate text.
