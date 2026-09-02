# Tutor 对话式学习工件任务树

## Parent

- `08-30-tutor-conversation-learning-artifacts` — source requirements、跨 child 设计、最终验收与集成复核；不作为常规实现目标。

## Tree

~~~text
01 Artifact Authority and Conversation Protocol
├─ 02 Teaching Orchestration and Branch Scheduling
├─ 03 Inline Artifact Shell and Safe Markdown
│  ├─ 04 Code Editor and Isolated Browser Preview
│  ├─ 06 Teaching Demonstration Artifacts
│  ├─ 07 Knowledge Checks Hints and Remediation
│  ├─ 08 AI Code Review Learning Artifact
│  ├─ 09 SQL Learning Workspace
│  └─ 10 Source References and Document Drawer
├─ 05 Execution Results and Runtime Presentation
└─ 11 Learning Item Bank and Agent Review

01 + 02 + 03 + 04 + 05 + 06 + 07 + 08 + 09 + 10 + 11
└─ 12 Artifact Integration QA and Rollout
~~~

## Dependency Notes

- 01 是公共 DB/API/Snapshot/SSE contract 基础。
- 11 可与 01 并行完成离线 catalog，但 online candidate 接入等待 01/02。
- 02 和 03 等待 01；03 只负责 Desktop shell，02 只负责 backend teaching/branch authority。
- 05 在 04/09 前稳定 SafeExecutionResult v2 与 test-result artifact。
- 04 等待 03/05；06 等待 02/03/04/11；07 等待 01/02/03/11。
- 08 复用现有 model review authority并等待 03/05/07/11。
- 09 等待 03/05/07/11；10 等待 01/03。
- 12 等待全部功能 child 完成，拥有跨层修复、文档、验证和 rollout，不重复各 child 业务实现。

## Recommended Start Order After Fresh Approval

1. 01 Artifact Authority and Conversation Protocol
2. 11 Learning Item Bank and Agent Review（可与 01 分阶段并行，但避免重叠 schema 写集）
3. 02 Teaching Orchestration and Branch Scheduling
4. 03 Inline Artifact Shell and Safe Markdown
5. 05 Execution Results and Runtime Presentation
6. 04 Code Editor and Isolated Browser Preview
7. 先通过 HTML vertical slice
8. 06/07/08/09/10 按 disjoint write set 交付
9. 12 Artifact Integration QA and Rollout

## Status

截至 2026-09-02，Child01-Child12 已按依赖完成实现、质量门、提交与归档；父任务未作为业务实现目标启动。最终 AC1-AC20、跨层 contract、schema/cutover、Desktop/Tauri、安全、回滚和非声明验收均已完成，证据见 acceptance-test-plan 与 tutor-harness-release-readiness。
