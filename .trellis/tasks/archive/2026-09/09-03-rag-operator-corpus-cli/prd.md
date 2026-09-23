# RAG Operator Corpus CLI

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child阶段I只交付手工CLI，不暗中加入scheduler。后续自动作业复用domain治理service，以独立v2授权驱动，不让模型执行任意CLI。旧manual路径和权限保持；新增worker属于阶段II实施包。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Goal

Provide a local operator-only, auditable manual workflow for fixture/future fetch reindex, validation, diff, activation, rollback, retirement and status without adding HTTP, Desktop or scheduled control surfaces.

## Dependencies

- Child 01 owns Subject/version/source-scope identity.
- Child 02 owns corpus lifecycle persistence and active-pointer CAS.

## Requirements

- Add a service layer and thin `argparse` CLI for `status`, `reindex`, `validate`, `diff`, `activate`, `rollback`, `retire`.
- Phase-1 acceptance uses deterministic fixture mode; fetch mode must remain explicit and never run from tests, startup, scheduler or learner requests.
- Mutating commands require idempotency; activate/rollback also require expected generation and exact summary hash where applicable.
- Per-source failure is isolated and all outputs are bounded structured JSON.
- Machine validation never auto-promotes a candidate.
- Candidate, validation and activation receipts are auditable and replay-safe.
- No maintenance route, admin identity, remote endpoint or Desktop UI is added.

## Acceptance Criteria

- [x] Every command has deterministic success, replay, validation-error and conflict projections.
- [x] Fixture reindex builds an isolated candidate and never changes the active pointer.
- [x] Validate/diff do not activate; activate requires validated candidate, generation and summary hash.
- [x] Rollback points to an earlier published corpus without deleting history.
- [x] Retire refuses the active corpus.
- [x] Route and worker schedule inventories prove no remote or automatic operator path was added.
- [x] CLI tests, service tests, Ruff and Mypy pass.

## Out of Scope

- Scheduled jobs.
- Web/admin/Desktop control surfaces.
- Production embedding configuration.
- Learner-visible corpus activation.
