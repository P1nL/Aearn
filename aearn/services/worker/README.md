# Worker Service

Celery worker for Aearn durable background and interactive wakeup jobs. PostgreSQL is
the authority for every queue/lease lifecycle; Redis/Celery only delivers wakeups and
periodic reconciliation.

Current registered tasks:

| Task | Queue / priority | Purpose |
|---|---|---|
| `health.ping` | default | Worker connectivity smoke check |
| `tutor.interactive.dispatch` | `tutor-interactive` / 9 | Claim one durable interactive dispatch job and invoke the existing finite Harness dispatcher |
| `tutor.interactive.reconcile` | `tutor-interactive` / 8 | Recover pending, retry-ready, or lease-expired interactive jobs; Celery beat schedules it every 5 seconds |
| `tutor.proactive.scan_due_signals` | `tutor-proactive` / 5 | Global verified-only safe-signal scan |
| `tutor.proactive.drain_candidates` | `tutor-proactive` / 5 | Claim proactive candidates through PostgreSQL policy/lease checks |
| `tutor.curation.drain` | `tutor-curation` / 1 | Drain redacted context-summary/memory curation jobs when policy enables them |

Interactive HTTP acceptance creates or rearms `tutor_interactive_dispatch_jobs` in the
same transaction as the learner input and initial public conversation events. A failed
Celery publish therefore does not lose the turn: the job remains in PostgreSQL for the
local fast path or the periodic reconciler. Duplicate tasks are fenced by job owner,
lease generation, expiry, and the existing Tutor run lease.

The worker and beat load configuration from `aearn/.env` and default to local
PostgreSQL/Redis on `127.0.0.1`. Start both in local development; `aearn/scripts/start-dev.ps1`
manages their PID and logs.
