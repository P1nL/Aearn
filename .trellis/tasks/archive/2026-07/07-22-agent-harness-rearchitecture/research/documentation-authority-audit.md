# Documentation Authority Audit: Harness Rearchitecture

**Recorded:** 2026-07-24  
**Scope:** parent planning only. This audit changes no runtime code, learner data,
deployment state, or published source document.

## Observed Baseline

- `docs/README.md` routes product, frontend, API, database, LangGraph, QA, and
  setup documents as the current source-of-truth set.
- Those substantive documents predate the Harness parent task created on
  2026-07-22. The later 2026-07-24 files under `docs/.obsidian/` are editor
  configuration, not target-product updates.
- `docs/current/Aearn/current-state-audit.md` records API/route drift and the
  need to refresh portions of the API/frontend source documents.
- Legacy product and LangGraph docs describe distinct onboarding, learning,
  review, resume, and notes flows; the parent target replaces product
  orchestration with a bounded single Tutor Harness.
- A concrete conflict is reset semantics: the legacy baseline retains
  profile/preferences, while the target cutover deletes legacy learner
  profile/preferences but preserves local identity, provider/model configuration,
  and UI settings.

## Authority Decision

Current documents are **legacy/current baseline evidence**. Current code,
tests, schema, routes, and configuration establish runtime facts. The approved
parent planning artifacts establish the Harness target. Phase 0 must publish a
linked transition contract and delta matrix before a child relies on target-only
behavior.

## Per-child Review Questions

1. Which factual current behavior is retained, adapted, or retired?
2. Which legacy document applies, and which target section replaces it?
3. Which API, event, schema, reset, or UI contract must exist first?
4. What evidence proves the child preserves safety and user-visible behavior?
5. What remains reversible before confirmed cutover?
