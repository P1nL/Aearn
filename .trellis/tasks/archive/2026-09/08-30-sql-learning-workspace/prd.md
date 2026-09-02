# SQL Learning Workspace

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

交付对话内 SQL Editor/Schema/Result workspace，显式执行公开查询并以隐藏测试安全判断完成。

## Scope

- SQL artifact presentation/action
- Editor/Schema fixed split与narrow stack
- Schema tree/PK/FK/复制
- public table_result_v1
- SQLite只读query policy
- Tutor evaluation/test result接入

## Requirements

### R1

- SQL不实时执行，只有Run触发

### R2

- 宽屏Editor/Schema 50:50固定，结果全宽底部；窄屏上下

### R3

- Schema只显示published public tables/columns/types/relations

### R4

- 名称可复制但不自动插入/聚焦

### R5

- Run public dataset返回bounded grid；hidden dataset只返回test summary

### R6

- 只允许SELECT/WITH只读语句，拒绝DDL/DML/ATTACH/PRAGMA/extension/file access

### R7

- 全部测试通过直接完成

## Acceptance Criteria

- [ ] 当前SQL runner columns/rows不再丢失
- [ ] grid列<=32、默认行<=50、硬上限、cell/payload有界
- [ ] public/hidden dataset泄漏测试通过
- [ ] copy交互不改变editor selection
- [ ] syntax/runtime/test failure结果和Tutor评价正确
- [ ] responsive/keyboard/overflow/large cell通过

## Out of Scope

- 连接Aearn PostgreSQL业务库
- 任意数据库/网络连接
- 实时自动查询
- SQL管理工具或多statement写操作

## Dependencies and Ordering

- 依赖Child01/03/05/07/11

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
