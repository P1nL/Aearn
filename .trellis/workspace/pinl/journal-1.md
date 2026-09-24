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


## Session 3: Tutor semantic direction recovery
<!-- trellis-session: v=2 fp=a3b7a1c978da8157 -->

**Date**: 2026-09-04
**Task**: Tutor semantic direction recovery
**Branch**: `codex/semantic-planning-language-resolution`

### Summary

Implemented generic semantic chat-direction recovery across Harness, Codex plan drafting, LearningPlan and LessonTeaching; added closed direction actions, durable correction receipts, bounded intake, atomic Runtime terminal cleanup, immutable Skill versions, regression coverage, and documented one approved real-provider turn. Related tests, Ruff, Mypy, Desktop checks, Trellis validation, and scoped diff checks passed.

### Git Commits

| Hash | Message |
|------|---------|
| `287d53d` | feat(tutor): recover from conversational direction drift |

### Status

[OK] **Completed**


## Session 4: 提交工作树并整理仓库结构
<!-- trellis-session: v=2 fp=6cc00d3da6e1d884 -->

**Date**: 2026-09-05
**Task**: 提交工作树并整理仓库结构
**Branch**: `codex/semantic-planning-language-resolution`

### Summary

核实并提交 executor CLI 入口修复；新增根目录导航，精确忽略 Python 欢迎缓存，截图迁移到 tmp/repository-cleanup 且 SHA256 不变。独立复核链接和忽略范围、diff 检查通过；未运行 executor。归档自动提交遇到未跟踪旧路径 pathspec，已按归档目录精确提交。

### Git Commits

| Hash | Message |
|------|---------|
| `30a92a5` | fix(executor): use registered CLI entry point |
| `c1a8080` | chore(repo): organize repository navigation and local artifacts |

### Status

[OK] **Completed**


## Session 5: Python LessonDocument 有界修复与安全诊断
<!-- trellis-session: v=2 fp=f5c7934d3df8e2f9 -->

**Date**: 2026-09-08
**Task**: Python LessonDocument 有界修复与安全诊断
**Branch**: `codex/semantic-planning-language-resolution`

### Summary

完成共享一次修复预算、安全反馈与私有审计、prepare replay DTO 和 Desktop 回归。独立审查通过；后端41测试、桌面最终38测试、Ruff/Mypy/tsc/lock及fake浏览器11块正文恢复通过。独立测试库已清理，未调用真实provider或修改用户课程数据。实际提交分支codex/semantic-planning-language-resolution；仅归档本任务，保留Obsidian并行改动，未push。

### Git Commits

| Hash | Message |
|------|---------|
| `ed2b1d6` | fix(lesson): add bounded authoring repair and safe diagnostics |

### Status

[OK] **Completed**


## Session 6: RAG Subject contracts implemented and verified
<!-- trellis-session: v=2 fp=0a1e2fdf6fe3af49 -->

**Date**: 2026-09-23
**Task**: RAG Subject contracts implemented and verified
**Branch**: `main`

### Summary

GPT-6-Sol implement/check; 48 offline tests plus Ruff/Mypy/lock passed; no live corpus or public rollout.

### Git Commits

| Hash | Message |
|------|---------|
| `3d54036` | feat: add guarded RAG subject capability taxonomy |

### Status

[OK] **Completed**

### Next Steps

- Versioned corpus authority in isolated disposable PostgreSQL database.


## Session 7: Versioned RAG corpus authority verified
<!-- trellis-session: v=2 fp=6c661d7d2d468d8c -->

**Date**: 2026-09-23
**Task**: Versioned RAG corpus authority verified
**Branch**: `main`

### Summary

Six shared corpus tables; guarded lifecycle/CAS/replay and savepoint atomicity. Final 37 DB, 50 legacy compatibility and 48 offline tests passed. Three disposable DBs removed; no live fetch or public rollout.

### Git Commits

| Hash | Message |
|------|---------|
| `eab2c58` | feat: add versioned RAG corpus authority |

### Status

[OK] **Completed**

### Next Steps

- Existing operator corpus CLI child; explicit fixture mode and isolated database only.


## Session 8: Local RAG corpus operator CLI verified
<!-- trellis-session: v=2 fp=fd5d9a2fc96eaab4 -->

**Date**: 2026-09-23
**Task**: Local RAG corpus operator CLI verified
**Branch**: `main`

### Summary

Fixture-only seven-command CLI. 114 tests, 60 actual CLI processes, 10 Subject fixture matrix and documented PowerShell example passed. Two disposable databases removed; fetch explicitly not ready, no public rollout.

### Git Commits

| Hash | Message |
|------|---------|
| `4b9a9fe` | feat: add local RAG corpus operator CLI |

### Status

[OK] **Completed**

### Next Steps

- Existing bounded hybrid retrieval and coverage child; exact-scope FTS and disabled/fake embedding only.


## Session 9: Bounded RAG retrieval verified
<!-- trellis-session: v=2 fp=cbe2b0fc321278fe -->

**Date**: 2026-09-23
**Task**: Bounded RAG retrieval verified
**Branch**: `main`

### Summary

177 tests passed; readonly exact-scope probes and deterministic replays; synthetic only, no public cutover; owned temporary databases removed; local commit only.

### Git Commits

| Hash | Message |
|------|---------|
| `a42f3e7` | feat: add bounded exact-scope RAG retrieval and coverage |

### Status

[OK] **Completed**

### Next Steps

- Continue existing 09-03-rag-plan-preflight-migration-proposals child05.


## Session 10: Shadow RAG plan preflight verified
<!-- trellis-session: v=2 fp=9eab12e50b1baafd -->

**Date**: 2026-09-23
**Task**: Shadow RAG plan preflight verified
**Branch**: `main`

### Summary

191 tests passed, 35 readonly checks, 167 table fingerprints unchanged; default-off projection only; two disposable databases removed; no public cutover or push.

### Git Commits

| Hash | Message |
|------|---------|
| `8a6273c` | feat: add shadow RAG plan preflight and migration proposals |

### Status

[OK] **Completed**

### Next Steps

- Continue existing child06 09-03-rag-shadow-integration-fixtures-docs.


## Session 11: RAG shadow integration verified
<!-- trellis-session: v=2 fp=cb623d2ba1720906 -->

**Date**: 2026-09-24
**Task**: RAG shadow integration verified
**Branch**: `main`

### Summary

330 tests passed, full Ruff/Mypy and Desktop build passed; CLI replay, readonly adapter and safe rejection proofs; two disposable DBs removed; phase I only, no public release or push.

### Git Commits

| Hash | Message |
|------|---------|
| `53cf28d` | feat: integrate guarded RAG shadow adapters and fixture demo |

### Status

[OK] **Completed**

### Next Steps

- Return to existing RAG parent for phase I acceptance reconciliation; do not start phase II.


## Session 12: RAG A material contracts delivered
<!-- trellis-session: v=2 fp=e4602d5c645625cc -->

**Date**: 2026-09-24
**Task**: RAG A material contracts delivered
**Branch**: `main`

### Summary

A pure contracts and default-deny policies implemented, independently reviewed, verified and archived; Tavily/runtime fallback remains future B/D work.

### Main Changes

- Strict material/source contracts, actor-purpose authority, exact claim receipts, four default-off flags; no public wiring.

### Git Commits

| Hash | Message |
|------|---------|
| `1bbf364` | feat: add guarded RAG material and source contracts |

### Testing

- [OK] 150 passed, 7 exclusive-DB tests skipped; new A suites 76 passed; Ruff, Mypy281, offline lock passed.

### Status

[OK] **Completed**

### Next Steps

- Plan B1 controlled Tavily search and persistent budgets; quota exhaustion routes to existing-library materials, no native-search fallback.
