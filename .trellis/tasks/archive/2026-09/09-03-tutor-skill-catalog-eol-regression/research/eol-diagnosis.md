# 2026-09-03 Skill Catalog EOL 故障证据

## Runtime evidence

- Ports 1420, 8001, 5432, and 6379 were listening.
- API health and conversation snapshot requests returned 200.
- `POST /api/tutor/conversations/2d8e1802-d899-4807-b1cc-b7015f4c7798/inputs` returned 500.
- `api-dev.err.log` identified `SkillCatalogValidationError` at raw-byte instruction hash validation.
- Codex worker reported `deepseek-v4-flash` ready; provider availability was not the failure.

## Byte evidence

- `tutor.lesson-teaching/1.2.0/instructions.md`: manifest expected hash equals LF-normalized bytes; current working bytes are CRLF.
- `tutor.lesson-teaching/1.2.0/evals.json`: manifest expected hash equals LF-normalized bytes; current working bytes are CRLF.
- Diagnostic result: `HASH_MISMATCHES=2`.
- `git ls-files --eol` reports `i/lf w/crlf` for both files.
- `git check-attr` reports `text=set, eol=lf` for both files.
- `core.autocrlf=true` explains the stale working-tree materialization; adding attributes does not retroactively rewrite existing files.

## Safe repair boundary

Rewrite only the two working-tree resources to LF, preserve reviewed content and manifest hashes, keep the five legacy CRLF overrides, and never run repository-wide renormalization in the dirty checkout.
