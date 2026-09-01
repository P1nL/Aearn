# Learning Item Bank and Agent Review

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

建立可版本化、可验证、可审核、可Pilot和可退役的Learning Item Bank，作为所有对话工件的受控内容来源。

## Scope

- Item blueprint/public/private/version/publish model
- YAML/JSON source与validate/verify/build/import工具
- AI draft generation seam
- standard answer/runtime/rubric/difficulty/remediation验证
- 独立子代理审核和裁决
- risk-tier pilot/publish/retire与telemetry

## Requirements

### R1

- 人工定义knowledge/blueprint/publish policy，AI只生成draft

### R2

- public/private严格分离，hash/version immutable

### R3

- 生成代理不能审核自己的题

### R4

- review roles curriculum/difficulty/technical/ambiguity/security/adversarial独立

### R5

- deterministic/security/unique-answer blocker一票否决

### R6

- 低风险agent-reviewed->pilot->自动晋级；中风险机器执行+代理+pilot数据；高风险人工最终批准

### R7

- online Tutor只能获得published safe handle/candidate summary

### R8

- 题目修改生成新version并使旧review失效

## Acceptance Criteria

- [ ] 所有item kind有strict schema和source references
- [ ] code/sql/demo/review标准答案/事件/测试可机器验证
- [ ] 答案歧义、Hint泄漏、rubric错配、malicious Markdown被拒绝
- [ ] review reports绑定content hash且blind/独立
- [ ] pilot异常可自动quarantine/retire，新会话不再选，历史可读
- [ ] authoring CLI不直接修改生产DB且import幂等

## Out of Scope

- 通用CMS/可视化后台第一版
- 在线实时未验证出题
- 真实provider质量声明
- 允许多数票覆盖安全失败

## Dependencies and Ordering

- 可独立构建shared catalog；online integration依赖Child01/02
- 为Child06/07/08/09提供published fixtures

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
