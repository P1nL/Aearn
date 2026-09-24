# A设计：严格合同与离线权限判定

> 2026-09-24：已进入in_progress，执行本文A写集；旧planning描述为建档历史。Tavily真实客户端、预算持久化及知识库回退路由仍属于后续B/D。

## 审批及范围

用户已批准A实施；A的业务范围仍是合同/策略/默认关闭配置，目前该范围代码与离线验证完成。既有main公开来源实测单独留证，不把网页工具操作计作B/C实现；本轮代码验证未新增真实搜索。当前等待提交授权，不自动进入B。

## 分层接口

发现路由补充（用户最新决定，替代原生联网接力）：优先复用已有知识库的合格教材，再以Tavily补足覆盖；Tavily额度耗尽后停止新增搜索，只对剩余缺口执行知识库检索、跨章节重组及有依据的教学编写。知识库材料必须实际存在、可读取、版本适配且用途获准；教材用途不自动获得评分用途。返回逐单元覆盖与来源绑定，未补足的缺口保持未就绪，不用模型记忆伪装教材，不因部分缺口阻断其他材料已就绪且课程必需前置已满足的单元；本单元材料齐全不等于可以越过前置依赖，教学准入与材料覆盖分开。无新增模型提供方、原生联网或其他搜索后备路径；已有材料也不能绕过撤权/版本/用途检查。

1. 模型侧建议：LearningMaterialDemand、SourcePreference、SourceDiscoverySuggestion及untrusted SourceCandidate。建议不含可授予权限的actor/root/余额；字段严格、冻结、extra-forbid、有界，用户对话/代码/token不直接进入公开查询。SourceDiscoveryDemand不是模型可签发输入，只由服务端验证建议后生成，绑定去身份化查询投影、受信actor、policy与canonical预算委托。
2. 服务端上下文：actor、enabled gates、policy/version/generation、权限和canonical预算委托由受信接口解析，不能从模型DTO接受“我是管理员/余额充足”。A只定义port和判定，真实身份/账本落地归B；没有受信resolver默认拒绝。
3. 证据与用途：SourceAssessment、VerifiedClaim、RagEvidenceBinding草案保留exact Subject/version、内容/revision/hash、用途、验证方法及适用范围。声明元数据不是证明，canonical hash不是签名；只有解析到服务端receipt才有权参与判定。
4. 四个关口：可探查、可存储、可作教材、可支撑正式评估。软偏好不能替代任一关口；查到入口不等于读到正文，读到正文不等于合格入库。

## A不承诺的能力

Tavily已由用户选定为首批搜索提供方，研究探测成功但未接入运行时。预算接口需考虑账户统计与单次receipt不一致；补充设计见research/tavily-budget-contract.md。A仍仅定义合同，原子预留、持久化、不确定消费和对账归B1，不扩大本任务实现范围。

- 不实现DNS解析/网络fetch/搜索SDK、实际lease或费用台账；纯URL规范化/策略判定不声称已阻止运行时DNS重绑定。
- 不实现完整网页可靠性评分、例子沙箱、claim真值认证或真实item发布。A仅拒绝缺失/错误作用域/用途/来源的证据引用，后续C签发真实receipt。
- 不新建schema、Celery任务、beat、API、公开课程或Desktop入口，不改变现有fixture哈希和trust语义。

## 关键设计

- URL作为untrusted候选只能交发现端口；正式证据请求只使用服务端handle/scope，不含任意URL、SQL、DB target或可执行命令。
- source origin与usage admission分离。个人博客可以是main_teaching，但不能靠origin/点赞自动取得assessment_evidence。
- SourceCandidate分别表达入口/正文/repo文件、文档revision与抓取完整性；prefix hash必须标范围，不得当整篇文档hash。真实探查中的HTTP200不赋予正文/用途/版本适用事实。
- VerifiedClaim只证明其记录的环境/输入/语义范围，多个同源转载不成为独立佐证；模型“我执行过”不是execution receipt。
- 准入判定绑定需求hash、actor/action、Subject/version、policy/授权generation、预算root/委托及用途。model_copy绕验证后也应重新验证关键边界。
- 四个开关独立false；缺配置/过时generation/未知actor/无预算委托返回有界reason，不包含秘密。
- 开关/拒绝/无外部调用的证明只覆盖A新增纯逻辑及其port，不代表当前所有CLI、网络或消费者已受新开关控制；旧v1链路仍按原合同兼容。真实入口强制检查归B/C/D及其独立验收。
- A的DTO与只读resolver协议不是实际验真、签名、预算预留或来源准入服务；测试中的正例仅用标记清楚的合成server context证明判定规则，不作为B/C实跑证据。
- 所有纯函数与clock敏感逻辑显式注入时钟，避免用真实当前时间使单元测试不稳定；不在模块import发网络或读业务DB。

## 最小修改集

grounding/autonomous下新增contracts、access_policy、source_policy、source_preferences、assessment_contracts及必要__init__；core/config.py只加独立false字段；tests/grounding增加合同、权限、默认关闭/隔离与旧fixture兼容测试。不得因“真实搜索已获准”引入B实现或真实搜索默认测试。
