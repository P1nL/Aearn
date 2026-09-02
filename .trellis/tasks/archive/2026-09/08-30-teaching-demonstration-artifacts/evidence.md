# Child06 implementation evidence

Date: 2026-09-02

## Implemented boundary

- Only published `demo_v2` Learning Item handles materialize a demonstration. Provider/model input cannot supply or alter source, steps, expected events, or duration.
- Static demonstrations use deterministic 6–30 second step durations, split overlong source into bounded steps, and complete only after foreground/current/60%-visible/render-ready elapsed time.
- Interactive demonstrations complete only with exact expected event key plus canonical bounded JSON payload and current Preview nonce/generation/continuous sequence evidence.
- One append-only `tutor_demonstration_completion_receipts` row backs one completion; replay returns the same result, conflicting evidence fails closed, and no Attempt/mastery/progress is created.
- Expected interactive event continuations retain higher priority than static display timers; ordinary learner messages remain higher priority than either and prevent duplicate next Turns.
- The Desktop renderer is read-only, never creates a draft or editor/paste surface, and runs interactive source only through Child04’s isolated native Preview host.
- Static timer state remains in process memory: visibility, focus, mount/identity, or render-readiness loss pauses it; app/reopen/remount restarts unfinished timing. Reduced motion uses discrete progress.

## Verification

| Gate | Result |
| --- | --- |
| Focused PostgreSQL/API tests (`test_teaching_demonstrations`, branch continuation, schema manifest) | 25 passed |
| Full API suite excluding `real_provider` | 837 passed, 2 deselected |
| API Ruff | passed (`ruff check app tests`) |
| API Mypy | passed (`mypy app`, 242 source files) |
| API compileall | passed |
| Desktop Vitest | 18 files / 132 tests passed |
| `pnpm --dir .\\aearn desktop:check` | passed; Vite transformed 131 modules |
| Rust Preview host tests | 9 passed |
| Rust fmt/check/clippy | passed |
| PostgreSQL bootstrap twice, receipt append-only, export/reset/delete/cutover | covered by focused tests |
| Trellis `task.py validate` | passed (implement 4 / check 2) |
| `git diff --check` | passed; configured LF-to-CRLF warnings only |

## Acceptance mapping

- Unrelated click/load/scroll cannot complete an interactive demo: exact runtime bridge token, child source-window, trusted click, current identity and continuous sequence validation.
- Duplicate event/timer produces one receipt and one continuation lineage: durable unique receipt and idempotent conflict/replay tests.
- Progress pauses/resumes exactly with visibility/foreground/render-ready state; reduced motion is discrete.
- Learner input outranks event/timer continuation and no duplicate next Turn is admitted.
- Read-only source has no editor, textarea, paste handler, Monaco model, or draft state.

## Non-claims

- No real provider or executor smoke.
- No Docker conformance, production image build/sign/publish, push, deploy, Tauri installer, or production data migration.
- The client-reported Preview event protocol is not remote or hardware attestation against a deliberately compromised authenticated Desktop client.
