# RAG A：资料需求、发现权限与用途审核合同

> 最终交付：2026-09-24代码提交1bbf364，A已归档。下文实施/待提交文字为阶段记录；以task.json completed和implementation-verification.md交付段为准。没有启动B1或push。

> 2026-09-24实施状态更新：当前会话已绑定本子任务，task.status=in_progress，用户已批准执行。以下旧planning叙述为建档历史，不再阻止A实施；范围仍仅为本PRD的纯合同/策略/默认关闭与离线验证。

## 授权与当前状态

用户已确认启动修订版A；原话与边界见research/user-approval.md。A纯合同/策略/默认关闭及离线验证已完成，独立check与main最终复跑通过，待提交授权。验收见research/implementation-verification.md。不得把A批准扩成B–E/生产启用许可。

## 目标

建立模型教材需求、混合来源发现、第三方分用途审核所需的严格内部合同和默认关闭策略，为B的作业/搜索/抓取及C的真实准入提供不可绕过的输入边界。来源可读性与正式评分证据分开，既有fixture/v1合同不改。

## 依赖与确认事实

- 父phase-ii-prd/design/implement v2、source-selection-extension，已确认第三方可主教材及评分claim独立验证门槛。
- 阶段I01/02/03/04/06已提交归档；现行17来源/22入口是注册信息，不是实时已审核教材池。
- 当前没有真实DiscoveryAccessPolicy、job budget authority或新的SourceUsageAdmission可用；A必须定义port/default deny，不能伪装它们已上线。
- main持有真实网页核对会话；本轮来源读取不是自动抓取管线实现，也不构成真实corpus admission。

## 需求

用户最新决定（替代模型原生联网接力）：Tavily额度耗尽后，剩余材料缺口仅从已有知识库中已审核、版本适用且用途获准的教材检索补充，不增加联网模型或第三方搜索服务。允许模型基于这些教材重组解释与示例，但保留来源关联；模型内置知识不算知识库教材。已有教材仍不能覆盖的部分明确保留缺口，不静默删目标、不冒充完整。已有材料充分且课程必需前置已满足的单元可继续教学，不因外部搜索耗尽而整体停课。具体接线归B1/D，A仍仅定义合同。

产品优先级补充：用户明确要求课程材料完整性优先。以已确认课程范围内的覆盖缺口推动补充发现，不以固定搜索次数宣布就绪，不为省额度削减学习目标；免费额度不足时保留缺口并报告未就绪，不自动付费。16条仅为初次研究样本上限，不是正式课程上限。完整性与预算的解释见research/tavily-budget-contract.md首节；A不因此承担B/C的真实覆盖与预算实现。

1. 严格、冻结、有界的LearningMaterialDemand、SourcePreference、SourceDiscoverySuggestion、SourceCandidate、SourceAssessment、VerifiedClaim、RagBudgetDelegation及binding草案。SourceDiscoveryDemand由服务端签发，不接受模型自行提交actor/root/余额形成该权威对象。
2. 正式证据请求仍不收任意URL；SourceCandidate中的URL始终untrusted，仅由独立broker将来处理。软偏好/平台身份不能转化为授权。
3. 模型DTO与受信server context分离；actor、policy/generation、预算root/委托、验证receipt由服务端resolver解释，不相信模型自报余额或“已执行”。A不造实际持久化服务。
4. 分开判定探查、存储、教材用途、assessment用途；缺真实policy、撤权、scope/版本/用途错配默认拒绝。主教材许可不自动授评分权。
5. 四开关分别默认false：discovery/intake/activation/evidence consumer；旧题库或public course flag不能连带开启。
6. 默认测试无网络、DB、provider或worker；新增真实公开核对记录只在research，不进入app import或默认测试。

## 验收标准

- [x] AC1：严格DTO拒绝多余权限字段、无界输入、错Subject/version/用途、重复/矛盾引用，关键model_copy旁路重验。
- [x] AC2：候选URL只在候选端口；正式请求拒绝URL/SQL/DB target/命令，平台热度与soft preference不能覆盖硬policy。
- [x] AC3：缺server context/resolver、未知actor、伪造root/usage及过时generation均fail closed；散列一致不当作授权签名。
- [x] AC4：探查/存储/main_teaching/supplementary/assessment分别有判定；候选或只获主教材许可的证据不能成为评分依据。
- [x] AC5：claim引用绑定版本、内容hash、适用范围和服务端验证receipt；缺独立性/缺执行receipt或来源错配拒绝，不把模型文本作为真实验证。
- [x] AC6：四gate默认关闭且相互独立；A新增纯判定/port的关闭路径无外部调用，不宣称既有CLI或所有runtime已接新flag。真实B/C/D入口强制门禁另验；默认值不能给scope授权。
- [x] AC7：旧fixture-v1内容与哈希、来源/公开课程映射、CLI与retrieval/citation消费者边界保持兼容。
- [x] AC8：无schema/worker/beat/public API/Desktop入口、网络SDK或模块import副作用；确定性测试、Ruff/Mypy/lock/diff通过。
- [x] AC9：记录A真实能力与后续B/C边界；公开网页探查结果不记为A已实现搜索、SSRF网络隔离、真实入库/评分验证或发布。

## 非目标

不实现搜索抓取客户端、DNS/egress隔离、DB台账、真实评审执行器、完整claim验证算法、自动source注册/准入、消费者接线或用户计划修改。必要的公开来源核对由main单独执行，不借此扩大产品写集。

## 风险与交付

访问/保留/用途许可及预算是独立部署门禁；未知依赖返回真实blocked。旧schema只允许既有trust标签，新第三方合同不能用伪标official规避；实际增量持久化归B/C。

交付：内部纯合同/策略/默认关闭配置、离线测试、短spec与兼容记录。真实运行、代码验证与规划研究分账。代码完成后独立check、main复验，提交按窄清单另行确认，不自动推送或开始B。
