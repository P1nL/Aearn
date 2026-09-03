# Root Cause Evidence

- Failing checkout: `D:\works\Aearn\Aearn`, branch `main`, HEAD `b09dd36`.
- Exact reproduced error: `psycopg.errors.CheckViolation: check constraint "chk_tutor_teaching_action_receipts_response_mode" ... is violated by some row`.
- Old fragment 080 accepts only `learner_response_mode IN ('none','composer')` and receipt v1/v2.
- Existing local database contains valid v3 Artifact receipts with `learner_response_mode='artifact'` and exact Artifact identity.
- Completed worktree bootstrap succeeds against the same database and contains fragments 120-200 plus early 080/110 v3 compatibility.
- `main..codex/tutor-conversation-learning-artifacts` is a 25-commit fast-forward; comparison found 57 dirty paths, 334 branch-changed paths, and zero overlap.


## Formal-checkout integration evidence

- Saved old HEAD, before/after status, SHA-256 hashes for 56 tracked dirty files, a binary dirty patch, and a copy of the one untracked Trellis workspace directory under `D:\works\Aearn\Aearn\.git\codex-backups\startup-bootstrap-20260903-090657`.
- Fast-forwarded formal `main` from `b09dd36` to `69dd41b`; all 57 status paths were preserved: 56 tracked files matched their pre-merge SHA-256 values, and the two files beneath the single untracked `.trellis/workspace/pinl/` directory matched its backup.
- Receipt v3 CHECK failure disappeared. Bootstrap then reached Learning Item import and exposed a second cross-checkout issue: all five curated sources match stored `source_path`, `source_hash`, `content_hash`, importer version, and deterministic validation receipt hash; only `source_file_hash` differs because the formal checkout has CRLF working-tree bytes under `core.autocrlf=true` while the original import used LF/mixed bytes.
- The user superseded old-data preservation with an explicit local-volume reset. No repository replay contract was changed and no immutable receipt was rewritten; final v3 compatibility is proven in a disposable database, while the formal checkout uses its fresh local volumes.
