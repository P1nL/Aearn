# Design: RAG Plan Preflight and Migration Proposals

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child仍shadow/default-off，不自动激活计划或迁移历史；单纯题库取证不强依赖迁移服务。阶段IIcorpus自动激活不改变本child计划/学习进度权限。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Services

- `PlanCoveragePreflightService`: resolves each draft node to exact Subject/version and composes corpus coverage, Lesson capability, published Learning Item and runtime/assessment facts.
- `PlanRepairProposalBuilder`: creates bounded alternatives from registry-owned compatible Subjects and capabilities.
- `ExistingTrackMigrationPlanner`: reads immutable active revision and creates a non-active predecessor-linked proposal projection or persistence record.

## Contracts

Each node result includes node identity, Subject/version, corpus and capability status, missing facets/capabilities, reason codes and allowed repair actions. Proposal hashes cover predecessor revision, exact node diffs, source/capability generations and policy version.

## Shadow Boundary

No public route invokes enforcement in phase 1. A default-off adapter may compute a report in tests or explicit internal tools. It cannot mutate plan confirmation, active pointers, progress or Lesson assignments.

## Safety

Alternatives come from server registry and compatibility rules. The model may provide learner-friendly wording in a future task but cannot define the proposal structure or destination Subject.
