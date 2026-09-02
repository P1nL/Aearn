# Knowledge Checks Hints and Remediation

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

交付可评分的结构化理解检查、D1-D5难度、不可变回答、补救/迁移和Overlay多级提示。

## Scope

- knowledge_check presentation/response/scorer
- difficulty profile与D(n)
- immutable answer/result Turn
- answer disclosure policy
- remediation/transfer selection
- H1-H3 overlay horizontal pagination与receipts

## Requirements

### R1

- 题型封闭且有唯一/明确评分规则

### R2

- 回答后原题只读，outcome正确/错误与artifact completion分离

### R3

- 概念题第一次错只提示+降一级补救，第二次明确讲解+迁移

### R4

- 事实题第一次错可直接解释；用户索要答案记录direct_answer

### R5

- 同知识点最多原题+一次补救

### R6

- Hint页首次显示才记录assistance，回看不重复

### R7

- popover覆盖工件表面、不reflow、不自动轮播

### R8

- D(n)只显示base difficulty，不随hint改变

## Acceptance Criteria

- [ ] 所有题型extra字段/非法选项/歧义评分fail closed
- [ ] 回答重放幂等，不同回答/stale version冲突
- [ ] remediation不是换序原题且难度最多降一级
- [ ] direct answer不能冒充independent mastery
- [ ] Hint H1/H2/H3 receipt exactly-once并可重载
- [ ] Popover desktop/narrow/keyboard/Escape/scroll行为通过

## Out of Scope

- 题库生产流水线（Child11）
- 普通Composer自由文本评价
- 多轮无限猜题
- 直接答案作为普通Hint第四页

## Dependencies and Ordering

- 依赖 Child01/02/03/11

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
