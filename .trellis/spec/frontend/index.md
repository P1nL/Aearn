# Frontend Development Guidelines

> Current development rules for the Aearn Tauri/React desktop.

---

## Overview

The formal desktop runtime lives under `aearn/apps/desktop/`. Current behavior is defined by the implementation and the documents indexed by `docs/README.md`; the protected HTML design under `docs/design/` is reference material, not runtime source.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Application shell, feature, contract, API, UI, and style layout | Filled |
| [Component Guidelines](./component-guidelines.md) | Component composition and interaction patterns | Filled |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks and stream/data behavior | Filled |
| [State Management](./state-management.md) | Local, global, server, and authority state | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Frontend gates and forbidden patterns | Filled |
| [Type Safety](./type-safety.md) | Contract and validation patterns | Filled |
| [Inline Artifact Shell and Safe Markdown](./inline-artifact-shell-markdown.md) | Snapshot v4/v5 parsing, safe Markdown, Artifact/branch UI state, scroll/focus, and browser gates | Filled |
| [Execution Result Artifact Presentation](./execution-result-artifacts.md) | Attempt v1/v2 parsing, concise result UI, output/table bounds, and return-to-source behavior | Filled |
| [Code Editor and Isolated Browser Preview](./code-editor-browser-preview.md) | Monaco draft/stale/run behavior plus Tauri child-webview isolation, capability, nonce bridge, watchdog, and responsive split | Filled |

---

## How to Use These Guidelines

Before frontend work:

1. Read the guide matching the touched surface.
2. Start from `docs/README.md`, then cross-check behavior against `docs/product/frontend-interaction-spec.md`, `docs/product/user-flows.md`, and the current API contract.
3. Treat the current Desktop implementation as the optimization baseline; do not rebuild the product inside `docs/design/`.
4. Run commands from `aearn/` or `aearn/apps/desktop/`, not the repository root.

---

**Language**: Project specs may remain English unless a task-specific rule requires another language. Trellis task artifacts under `.trellis/tasks/**` follow the repository's Simplified Chinese rule.
