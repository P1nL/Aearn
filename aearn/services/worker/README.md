# Worker Service

Celery worker for Aearn background jobs.

Current registered tasks:

| Task | Purpose |
|---|---|
| `health.ping` | Worker connectivity smoke check |
| `review.refresh_due_counts` | Counts currently due review items per active user |
| `review.generate_seed_bank` | Generates and persists a review seed bank for one user/knowledge point |
| `tutor.proactive.scan_due_signals` | Bounded target-only time-signal scan; no source is enabled by default |
| `tutor.proactive.drain_candidates` | Claims target proactive candidates through PostgreSQL policy/lease checks |
| `tutor.curation.drain` | Low-priority curation-job drain for Child 02 redacted outbox records |

The Tutor scheduler tasks are feature-disabled by default. They use separate
`tutor-proactive` and lower-priority `tutor-curation` queues, never replace the
legacy review tasks, and default to no provider/capability/domain call until a
later approved composition and cutover task owns activation.

The worker loads configuration from `aearn/.env` and defaults to local PostgreSQL/Redis on `127.0.0.1`.
