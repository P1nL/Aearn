# Journal - pinl (Part 1)

> AI development session journal
> Started: 2026-08-30

---



## Session 1: Repair Tutor Skill Catalog EOL regression
<!-- trellis-session: v=2 fp=d7c92ad8d939e128 -->

**Date**: 2026-09-03
**Task**: Repair Tutor Skill Catalog EOL regression
**Branch**: `codex/tutor-skill-catalog-eol-regression`

### Summary

Restored the published tutor.lesson-teaching 1.2.0 resources to manifest-authoritative LF bytes and committed exact Windows checkout rules while preserving five reviewed CRLF exceptions and unrelated dirty work.

### Main Changes

- Persisted Skill bundle default eol=lf with five exact legacy eol=crlf overrides.
- Added an executable raw-byte Skill integrity contract to the backend Trellis spec.

### Git Commits

| Hash | Message |
|------|---------|
| `1a4d648` | fix(tutor): preserve published skill bytes on Windows |

### Testing

- [OK] Full manifest scan: 8 manifests, 16 resources, HASH_MISMATCHES=0; catalog compiled with 8 skills.
- [OK] Skill Catalog pytest: 13 passed; Ruff and Mypy passed; API health returned 200.

### Status

[OK] **Completed**

### Next Steps

- No automatic learner-input retry was run; the user may retry in the Desktop when ready.


## Session 2: Semantic planning language resolution
<!-- trellis-session: v=2 fp=1e3a8670a74d82ab -->

**Date**: 2026-09-03
**Task**: Semantic planning language resolution
**Branch**: `codex/semantic-planning-language-resolution`

### Summary

Implemented bounded semantic language resolution for learning-plan drafting while preserving server authority, explicit-language auto-confirm, durable request replay, and feature-off rollback.

### Main Changes

- Added planning-intent-hint-v2 across Harness, Codex sidecar, decision gate, resolver, and persistence.
- Added immutable tutor.learning-plan-draft 1.0.2 and synchronized API/frontend/Trellis source-of-truth docs.
- Preserved the existing eight-option pending request; v2 applies only after cancel/recreate.

### Git Commits

| Hash | Message |
|------|---------|
| `946e85c` | feat(tutor): add semantic planning language resolution |

### Testing

- [OK] Focused PostgreSQL regressions: 24 passed.
- [OK] Isolated full API suite: 891 passed, 2 skipped; Ruff, Mypy, uv lock, Skill Catalog, Trellis validate, and git diff check passed.
- [OK] Desktop: 24 files and 161 tests passed; desktop:check passed; dev stack restored healthy.

### Status

[OK] **Completed**

### Next Steps

- Use the existing Cancel plan flow and create a new planning session to exercise v2 against the configured provider; no real-provider smoke was run in this task.
