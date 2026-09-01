# Learning Item Bank and Agent Review 技术设计

## Boundary

建立可版本化、可验证、可审核、可Pilot和可退役的Learning Item Bank，作为所有对话工件的受控内容来源。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- Git-owned source -> compiler -> canonical item/version hash -> DB shared immutable rows
- Private evaluation加密/限制读取，public projection单独serializer
- Verification adapters按item kind运行
- ReviewOrchestrator并行独立角色，Adjudicator只汇总不能覆盖deterministic gates
- Pilot metrics校准难度/歧义/异常但不自动改变production policy

## Data Flow

1. blueprint -> generated/manual draft -> validate -> verify -> agent reviews -> adjudicate -> pilot -> publish
2. runtime candidate query按knowledge/purpose/difficulty/capability/unused筛选<=8 handles

## Contracts and Invariants

- 人工定义knowledge/blueprint/publish policy，AI只生成draft
- public/private严格分离，hash/version immutable
- 生成代理不能审核自己的题
- review roles curriculum/difficulty/technical/ambiguity/security/adversarial独立
- deterministic/security/unique-answer blocker一票否决
- 低风险agent-reviewed->pilot->自动晋级；中风险机器执行+代理+pilot数据；高风险人工最终批准
- online Tutor只能获得published safe handle/candidate summary
- 题目修改生成新version并使旧review失效

## Affected Surfaces

- aearn/packages或services/learning/item_bank/（最终按spec定目录）
- DB shared item/version/private/publication/review tables
- authoring CLI/worker jobs
- teaching candidate adapter
- seed fixtures和item-bank tests

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- 停止publish/candidate admission，保留published历史
- 退役有问题version，不原地修改
- agent review feature关闭时高风险全部停在machine_verified
