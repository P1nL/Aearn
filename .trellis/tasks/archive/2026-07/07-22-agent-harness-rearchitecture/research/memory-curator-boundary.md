# Memory Curator / Context Compactor Boundary

## Status

Approved Phase 1 planning decision. This document is a target-design boundary,
not a statement about the current runtime or legacy documents.

## Problem

The Tutor must continue learning across days without placing an unbounded raw
conversation history in every model call. Durable state is the source of
continuity; a bounded Context Builder selects a small relevant slice for each
run. Curation may make that selection more useful, but it cannot become an
uncontrolled second Tutor.

## Contract

`Memory Curator` (also called `Context Compactor`) is an internal background
worker with these fixed boundaries:

| Area | Required behavior |
| --- | --- |
| Trigger | Only a durable terminal/checkpoint/evaluation/review/plan-change event or configured context high-water mark. Never each streamed token or an idle infinite loop. |
| Input | A redacted, ordered, transactional outbox row anchored to a user/conversation/run and closed event/input range. No arbitrary conversation read, raw prompt, provider payload, hidden test, secret, or trace body. |
| Output | An idempotent typed `context_summary` proposal or learner-inspectable `memory_entry` proposal. It cannot emit tutor text or a teaching decision. |
| Commit | Policy/service/repository validation owns commit. It checks ownership, evidence, confidence, provenance, retention/staleness, user setting, expected state, and idempotency. |
| Domain authority | Runner/evaluation/review/FSRS services record objective facts directly. Curator never changes plans, reviews, FSRS, attempts, messages, activity/inbox, execution, or any domain table directly. |
| Provider | Use the configured primary provider/model only, with lower curation token/call/frequency/wall-clock/retry budgets. No hidden specialist, cross-provider fallback, or task-based dynamic model routing. |

## Memory and Context Separation

- A context summary is a bounded, redacted checkpoint-like artifact scoped to
  its source range. It is not a learner fact and cannot by itself justify a
  learner-memory conclusion.
- A learner-memory inference requires evidence references, confidence,
  provenance, source scope, retention/staleness metadata, and learner-safe
  inspection/correction/deletion controls.
- A learner memory disable rejects new inferred-memory proposals and excludes
  disabled entries from future context. It does not rewrite visible conversation
  history or authoritative execution/evaluation/review facts.
- A hard background pause blocks Curator leasing. Provider failure is retained as
  a redacted pending/skipped/failed result and never changes provider/model.

## Child Ownership

| Child | Responsibility |
| --- | --- |
| 00 Harness contracts | Define `TutorContextBuilder`, context budget, checkpoint reason, and injectable compaction-request contract. |
| 02 State/traces/evals | Persist redacted ordered outbox rows and proposals; enforce ordering, idempotency, retention, and export redaction. |
| 04 Proactive scheduler | Supply low-priority curation queue, lease, budget, cooldown, retry, circuit-breaker, pause, and recovery primitives. |
| 05 Plans/memory/activity | Implement the guarded Curator and proposal/commit semantics; preserve learner controls and domain authority. |
| 06 API/SSE/desktop | Render learner-safe type/evidence/confidence/provenance/retention and correction/delete/disable controls without exposing Curator internals. |

## Proof Obligations

1. Duplicate outbox delivery cannot create a second proposal or committed entry.
2. Redacted exports, API responses, and UI never expose Curator prompts, raw
   source segments, model rationale, provider payloads, or protected traces.
3. Pause, memory disable, and curation-budget denial make no provider call.
4. Curator output cannot mutate plan/review/FSRS/attempt/activity/inbox/chat or
   execute code without an independent normal domain effect path.
5. Context construction remains bounded and a Curator request is never generated
   per token.
