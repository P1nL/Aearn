# D 教材语义修复：实施前的收敛设计（2026-09-27）

> 中间提案，供主会话审阅；不是通过验收或生产启用声明。2026-09-27 的真实 DeepSeek 两次请求只检验独立短草案修订，不是完整 D 规划链。第一次合法 JSON 把 SQL WHERE 教材细节误解为学习地点；第二次经明确说明后改正。

## 根因与不可退让边界

现有 D 保住 parent、goal/node 哈希、用途及 current C 授权，但模型写出的 `pace_summary`、模块说明和最终消息仍可能语义误读材料缺口。校验 JSON 形状、关键词或在错误文字后追加固定免责声明，都不能识别“学习地点＋免责声明”。不能把计划能力缩成仅改 `weekly_minutes`，也不能默默重写原模型候选。C 的正式证据、purpose、claim、generation、expiry 继续由现有确定性事务校验；模型或 reviewer 均不得把 gap 改成 ready。

## 合同和调用顺序

1. D server-only opt-in 先按当前 run/revision 加载持久 parent feedback、精确 parent、selection；组装有界 review facts：draft/selection digest、完整 node/goal/purpose、Subject/version/facets、covered/gap、gap 的教材领域含义、原始候选的 profile/modules/public message。该事实由服务端生成；任何字段超出上下文源/总 token 上限时明确拒绝，绝不 `[:N]` 后按全量审核。需用实际 serializer 做逐源 round-trip。模型与网页文本不能给这组事实授信。
2. Gateway 在每个已解析且通过基础安全校验的候选上调用 `MaterialSemanticReviewer` 一次，reviewer 输入为服务端事实及候选 digest，输出严格 verdict `consistent|inconsistent|uncertain`、闭集有界 issue path/code（比如 `material_facet_meaning_mismatch`、`material_readiness_overclaim`）。`uncertain`、无效 schema、provider/transport 失败一律 fail closed；仅明确不一致且正常的候选才向**同一个**既有 provider gateway 第二次尝试返回具体安全诊断。两次仍错误无 capability/append/binding。Reviewer 不验证 source authority，也不替代 C 授权。
3. Reviewer 使用项目已配置模型和客户端（不建第二付费服务）。硬上限是每个候选至多一次 reviewer 调用、每个 decision 最多现有两次候选尝试，因此本次 decision 最多两次附加调用；关闭客户端内隐式重试、限制输出 tokens/超时。分别在安全 receipt 中保留 provider 与 reviewer 的实际 usage、异常/未知 usage 仍标 unknown，不记零；两类调用都发生于 DB append 事务外。
4. 通过后由服务端在短事务写**非模型签发**的私有审查 receipt，绑定 user/session、run/input_revision、parent selection handle/digest、候选规范化 digest、verdict、reviewer 版本及安全 usage，不含原文、provider body 或密钥。Gateway 返回 accepted 前 receipt 已 durable；与 run lease/input revision CAS 对齐。Capability 在 append 的同一事务重算候选 digest 并查精确 receipt、selection 当前关联和 parent CAS。缺 receipt、错 digest、旧 run、取消或 reviewer 不确定均拒绝；其后仍做 current C selection/successor binding 的原子复核。历史 receipt 不自动给下一个 run 或修改稿授信。
5. reviewer 是概率性自由文本一致性复核：它能降低词义误读，不能证明所有任意自然语言的真值。确定性保证仅限 exact scope、目标/节点、C current 权限及 receipt/digest/fence。原始错误候选和第二次候选不在用户计划中静默替换；失败只能留安全诊断。

## 实施写集和需主会话协调

- 本代理：`learning/material_selection.py`、`material_planning_composition.py`、新的 `material_semantics.py`（或 reviewer 模块）、`plan_capability.py`、D learning tests；共享 `tutor/provider_gateway.py` 只做默认关闭的 review hook 与既有 2-attempt 循环复用。若必须把同连接 D consumer/receipt writer 传入 gateway，`interactive.py` 做最小 opt-in 接线并与主会话协调。
- 需要持久 receipt 时，先检查现有 provider/action receipts 是否能安全承载 exact candidate/selection digest；若不能，新 D 私表及 schema manifest 由主会话分配写集或批准串行合并，绝不挪用 C authority 表。不得写通用 context budget 模块、公开 DTO、C 来源授权、API keys、付费验收、commit/push。

## 验收

- 实际 dispatcher + 假 transport + 假 reviewer：首轮合法 JSON 误解 `WHERE` 为学习地点，reviewer 给领域原因；第二轮保留全部 goal/module 且修正材料含义，经 gateway/capability/DB 新 selection/binding 成功。替身只证明接线。
- 两轮不一致、reviewer uncertain/invalid/unavailable、usage unknown、超上下文边界、伪造/错 digest/错 run/旧 version、撤权：没有新 successor/binding，安全 receipt/诊断可追踪。现有 provider attempts 不突破 2，reviewer calls 不突破 2。
- D flag off 普通 factory 零 reviewer/D IO；隔离 PostgreSQL 原有正负/锁/回滚和旧 public 行为回归。真实 provider+正式当前 C 来源仍是独立验收，不以替身宣称通过。
