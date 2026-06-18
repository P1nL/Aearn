# Worker Service

Celery worker for Aearn background jobs.

Current registered tasks:

| Task | Purpose |
|---|---|
| `health.ping` | Worker connectivity smoke check |
| `review.refresh_due_counts` | Counts currently due review items per active user |
| `review.generate_seed_bank` | Generates and persists a review seed bank for one user/knowledge point |

The worker loads configuration from `aearn/.env` and defaults to local PostgreSQL/Redis on `127.0.0.1`.
