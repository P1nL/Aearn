# 2026-09-03 Execution Evidence

## Checkout integration

- Formal checkout: `D:\works\Aearn\Aearn`.
- Before: `main@b09dd36`; after: `main@69dd41b`, fast-forward only, ahead of `origin/main` by 25 local commits, no push.
- Branch delta: 334 paths. Existing status: 57 paths. Intersection: 0.
- Preservation: 56 tracked files matched their pre-merge SHA-256 values; the two files under the one untracked `.trellis/workspace/pinl/` directory matched its copied backup.
- Backup: `.git/codex-backups/startup-bootstrap-20260903-090657`; binary patch size 244,484 bytes. The first attempt to write the patch used an invalid `git --output` argument, reported an error, and was immediately repaired by generating the patch against saved old HEAD and the exact dirty path list.

## User-authorized local data reset

- Decision: user said `放弃旧数据` on 2026-09-03.
- Scope inspected before deletion: Compose project `aearn`, containers `aearn_postgres` / `aearn_redis`, named volumes `aearn_aearn_pgdata` / `aearn_aearn_redisdata`.
- Command: `docker compose -f .\aearn\infra\docker-compose.yml down -v` from `D:\works\Aearn\Aearn`.
- Result: only those two Aearn volumes and the Aearn network/containers were removed. `docker compose ... up -d` recreated both; PostgreSQL and Redis became healthy.
- Old local database/Redis data are intentionally unrecoverable because no database-volume backup was requested or created. Repository dirty patch is not a data backup.

## Bootstrap and regression

- Formal API cwd: `D:\works\Aearn\Aearn\aearn\services\api`.
- Fresh `python -m app.db.bootstrap` exit 0 twice: `Aearn database bootstrap complete.` both times.
- Formal focused matrix: schema manifest + repeat bootstrap + existing event-v3 compatibility, 6 passed in 3.04s; Ruff passed.
- Added regression in `test_tutor_teaching_artifact_commit.py`: commit a real Artifact-owned `teaching_action_receipt_v3`, run bootstrap twice, re-read exact receipt fields.
- Added fragment assertion in `test_tutor_teaching_session_postgres.py`: response mode and version shape must include Artifact / receipt v3 / policy v3.
- Worktree regression ran in a uniquely named disposable PostgreSQL database to avoid sharing raw Learning Item source-file hashes across CRLF/LF checkouts: 3 passed in 11.02s; Ruff passed; database dropped in `finally`.

## Startup

- Command: `pnpm --dir .\aearn dev` from formal checkout, exit 0.
- Final status: PostgreSQL/Redis healthy; API `127.0.0.1:8001` ready; Desktop `127.0.0.1:1420` ready; API/main worker/Codex worker/beat/Desktop tracked PIDs alive and command verified.
- Logs: API application startup complete; main worker and Codex worker ready; beat started; Codex runtime health ready with configured DeepSeek sidecar. No learner request or paid/provider teaching smoke was sent.

## Not executed

- No real provider smoke or learner message.
- No Docker executor conformance.
- No production image/Tauri installer build, sign, or publish.
- No push, deploy, production migration, or production data mutation.
- No cleanup or commit of pre-existing unrelated dirty files.
