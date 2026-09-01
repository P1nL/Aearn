# Child 03 Implementation Evidence

**Date:** 2026-09-01

## Delivered

- Desktop exact parser/types for snapshot v2/v3/v4/v5, `active_artifact`, eight closed Artifact presentations, Artifact detail/action responses, and exact depth-one branch groups.
- Internal AST `SafeMarkdown` with inert raw HTML, bounded directives, public-host URL policy, readable color checks, streaming fenced-code stability, tables, copying, and escaped syntax tokenization.
- Static Artifact renderer registry, inline shell, server-projected state/actions, process-local version-keyed UI/detail caches, one-time new-Artifact reveal, terminal collapse fencing, branch rail/grouping, container queries, visible focus, 44px controls, and reduced-motion handling.
- Source-of-truth and Trellis frontend spec updates.

## Review fixes

The Trellis check agent found and fixed:

1. technical placeholder accessibility labels;
2. StrictMode duplicate auto-scroll;
3. branch-summary/anchor and single-active-branch parser gaps;
4. recursive protected-marker coverage across snapshot items;
5. pre-terminal learner messages incorrectly triggering terminal collapse;
6. missing version-keyed lazy Artifact detail loading;
7. relative/local/IP Markdown navigation and missing visible code tokenization;
8. duplicate terminal state copy and long-content wrapping.

No unresolved Child03 code finding remained after the check pass.

## Automated gates

```text
pnpm --dir .\aearn\apps\desktop test
12 test files passed; 101 tests passed.
```

```text
pnpm --dir .\aearn desktop:check
tsc passed; Vite production build passed; 107 modules transformed.
```

The focused reviewer matrix passed 5 files / 72 tests. Scoped and repository `git diff --check` returned exit code 0; Git emitted only the existing LF-to-CRLF informational warnings.

## Real browser fixture

Target: `http://127.0.0.1:1420/artifact-smoke.html` served from this checkout by Vite. The fixture was temporary, used only learner-safe static DTOs, and was removed after evidence capture.

| Viewport | Width evidence | New Artifact | Focus | Branch interaction | Security/console |
| --- | --- | --- | --- | --- | --- |
| 1440x900 | document/body `1440 == 1440` | one shell, version updated to 2, `scrollIntoView` count 1 | focus remained on fixture input through authority update | resolved summary expanded and branch learner became visible | no overlay/contract error/script execution/unsafe link; 0 warning/error |
| 900x900 | document/body `900 == 900` | same | same | same | same |
| 390x844 | document/body `390 == 390` | same; Artifact width 324 within timeline 366 | same | same | same |

Action height was 44px and Artifact toggle height was at least 52px at all viewports. Raw `<script>` source remained visible inert text, no executable script element or unsafe global appeared, and the `javascript:` label was not a link. Normal mode used smooth reveal; a fixture-injected reduced-motion match in the real browser produced one `auto` reveal with focus preserved and no overflow. The CSS media rule is additionally covered by `ArtifactSourceGuards.test.ts`; this evidence did not change the host OS accessibility preference.

Screenshots are outside the repository under:

```text
C:\Users\32624\AppData\Local\Temp\aearn-child03-browser-2026-09-01\
```

## Non-claims

- No real provider request was sent.
- No real executor, Docker conformance, production image build/sign/release, push, deploy, production cutover, or production data migration was run.
- Placeholder renderers are typed seams for later approved children, not completion of Monaco/Preview/results/knowledge/review/SQL/source feature families.
