# RAG Plan Preflight and Migration Proposals

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child仍shadow/default-off，不自动激活计划或迁移历史；单纯题库取证不强依赖迁移服务。阶段IIcorpus自动激活不改变本child计划/学习进度权限。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Goal

Add default-off/shadow services that evaluate plan nodes against Subject, corpus, Lesson, Learning Item and runtime capabilities and generate immutable, explainable repair or existing-track successor proposals without changing public plan activation.

## Dependencies

- Child 01 owns Subject/capability identity.
- Child 02 owns corpus authority.
- Child 04 owns retrieval and coverage results.

## Requirements

- Define typed node source requirements: Subject id/version, required facets and required capabilities.
- Evaluate every node as supported, partial, insufficient or unavailable using server-owned facts.
- Generate bounded server-owned alternatives: replace node, delete optional node, downgrade assessment, defer Subject, wait for release.
- Core-goal insufficiency must produce blocked target behavior; optional gaps produce an explicit successor proposal.
- Existing unsupported tracks retain active plan/progress/assignment/Lesson failures; proposals are predecessor-linked and never auto-activated.
- Provider text may explain a proposal but cannot invent ids, targets or mutations.
- Phase 1 remains shadow/default-off and does not modify public plan-confirm routes or Desktop behavior.

## Acceptance Criteria

- [x] Supported, partial, uncovered core and fixture-only ecosystem nodes receive deterministic statuses.
- [x] Repair proposals contain exact node-level diff, reason codes, target handles and canonical hash.
- [x] `lc-overview`-shaped fixture with a core LangChain goal yields `wait_for_release` or blocked, not ordinary Python substitution.
- [x] User-unconfirmed proposals do not modify plan pointer, progress, assignment or Lesson state.
- [x] Duplicate proposal requests replay; stale source/plan versions fail closed.
- [x] Public plan confirmation behavior remains unchanged with feature gates off.
- [x] Focused tests, Ruff and Mypy pass.

## Out of Scope

- Learner-visible migration UI or routes.
- Activating successor plans.
- Public ecosystem courses.
- Model-selected repair targets.
