# Knowledge Checks Hints and Remediation 技术设计

## Boundary

交付可评分的结构化理解检查、D1-D5难度、不可变回答、补救/迁移和Overlay多级提示。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- DifficultyProfile字段化reasoning/concept/context/transfer/response/scaffolding
- DisclosurePolicy服务端给模型allowed_disclosure_level
- RemediationSelector按knowledge/purpose/difficulty/unused published item选handle
- HintOverlay前端按已解锁页渲染，向后翻页触发next-level action

## Data Flow

1. artifact active -> optional hint page -> respond action
2. score -> original completed -> Tutor evaluation/result
3. incorrect -> remediation successor；second incorrect -> worked explanation + transfer
4. correct -> mainline继续

## Contracts and Invariants

- 题型封闭且有唯一/明确评分规则
- 回答后原题只读，outcome正确/错误与artifact completion分离
- 概念题第一次错只提示+降一级补救，第二次明确讲解+迁移
- 事实题第一次错可直接解释；用户索要答案记录direct_answer
- 同知识点最多原题+一次补救
- Hint页首次显示才记录assistance，回看不重复
- popover覆盖工件表面、不reflow、不自动轮播
- D(n)只显示base difficulty，不随hint改变

## Affected Surfaces

- Learning Item/Practice contracts与scorer
- Artifact knowledge/hint services
- Teaching decision context/policy
- Desktop KnowledgeCheckArtifact/HintPopover
- difficulty/disclosure/remediation tests

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- 关闭dynamic knowledge artifact admission，保留现有Gate静态题
- 历史answer/hint receipts只读
- 不回填或重算旧mastery
