# RAG D：规划教材反馈与精确证据绑定消费

## 当前直接修复与提交授权补充

用户要求修复剩余收尾问题，完成后收尾当前与前面的工作并提交工作树，不推送。除已验证的 post-save capability 关闭与完成阶段非思考调用外，真实语义修订反复暴露旧 plan raw360 合同容量不足；按 `research/versioned-plan-payload-repair.md` 做有界、版本化、仅 planning 的1024容量升级。保留旧发布版本/普通能力限制及全部语义、目标、来源授权校验；不得靠重复碰运气、删目标或伪造终态凑通过。新实现仍须独立check和真实自然完成后才归档 D。

最终结果：D内部真实验收已通过，父/后继run均自然completed，后继v2及1条当前补充材料binding持久化、目标hash保留。最终domain字段违规在付费审核/执行前进入真实修复并成功；未放松领域限制。详见 `research/d-final-closeout.md` 与 `research/d-final-acceptance.json`，并保留最后补丁由主会话收尾而非子代理独立复核的边界。公开消费者/E/Gate仍未启用。

> 2026-09-27；状态：in_progress。用户已批准D实施，内部代码与隔离验收完成；未提交/推送，工作流收尾另行处理。

## 目标与用户价值
2026-09-27追加批准：修复真实全链路验收、资料语义与输出一致性、上下文预算边界。执行与诚实验收要求见research/repair-acceptance-plan.md；先前D隔离验收不代表这些追加项已完成。

让学习计划依据实际可用教材生成和修订，而不是模型先承诺完整课程、后台再凑材料。系统优先复用合格资料，反馈真实缺口，核验后冻结精确来源；学习者无需逐页审批资料，Tutor 仍负责组织讲解、示例和练习。

## 背景与权威依据
- 父任务 phase-ii-design.md:68-78 与 phase-ii-implement.md:65-81 明确 D 交付内部规划消费者、绑定及授权 fence；E 才做真实题库全入口联调和逐 scope 发布。
- 现有草案有 session/user/run/input_revision、draft_version/content_hash 和 predecessor；source_summary 只是展示信息，不是用途授权。child05 预检仅只读投影，尚未实现教材反馈修订/持久冻结。证据见 research/planning-consumer-seams.md:11-18。
- A 已有材料/用途/claim 合同；C 有 registered/candidate 正式用途授权和单 corpus authority。D 复用它们，不新建来源系统。证据见 research/evidence-authorization-fence.md:14-20。
- C 真实验收仅 WHERE/LIMIT 两个精确补充解释片段；机器回执与暂存许可截至 2026-09-26 21:26:59（北京时间），不能视作今天可用。C 未提交工作与无关更改保留，D 基线见 research/worktree-baseline.json。

## 功能要求
### R1 需求与真实内部消费
首批 Python 核心与 SQLite SQL。新草案或显式修订提出按节点/用途的教材需求，RAG 返回精确材料、覆盖及缺口，既有规划模型利用反馈修订，服务端重新核验并持久冻结。不能只交独立 helper 或模拟出来的成功报告。

### R2 草案身份与目标保护
需求、选择结果和绑定均关联当前 user/session/draft/version/content_hash、node/goal hash；模型建议不是 authority。旧反馈可作为受控 successor 的修订输入，但不得直接为新草案授信，修订后重新选择/核验。虚构 handle、旧异步回调、跨用户/节点和错版本必须拒绝；不删减核心目标伪造完整覆盖，不自动替换历史 active plan。

### R3 复用、缺口和自动处理
已有合格、适用材料足够时复用。existing_only 禁止新增外部发现、替代搜索 provider 和原生联网，不禁止既有规划模型处理资料反馈。未抓取登记入口、过期/撤权/错用途/错版本材料不是 ready。partial 按节点及前置依赖报告；缺口不触发逐页人工必经步骤，也不跳过正式 Gate。发现需求仅通过既有受控 B 端口提交，消费事务不联网。

### R4 精确用途与 claim
主教材 main_teaching、补充讲解 supplementary_explanation、正式评分 assessment_evidence 分开。冻结 exact 文档/revision/hash、chunk、来源准入和当前授权坐标，同时保留 corpus/registry/检索/覆盖信息。正式评分逐 claim 验证独立来源或真实执行证据；主教材通过不授评分资格。缺少可信 claim/执行 resolver 时明确拒绝，不从 SQL 行、模型自述或 C 补充片段推定通过。

### R5 当前授权与原子 fence
提供 resolve_evidence、check_current_authorization、assert_publication_fence。冻结和 fence 在调用方同一短事务重验当前授权、代次、期限与精确绑定；撤权/代次变化阻断并回滚。D 验证接口及隔离事务，题库 owner 保存其发布 receipt；后续供题仍须重验，不能靠旧绑定或异步隔离事件继续使用撤权材料。

### R6 兼容与隐私
新接入显式内部 default-off，关闭时零新增 DB/provider/发现 IO，旧默认路径行为不变。旧 v1 fixture/hash、shadow 边界、公开 DTO、历史 plan/track 和进度保持不变；只增加精确版本化的内部引用例外。新用户级记录纳入既有授权 reset/delete 生命周期，不记录原始 learner 对话、秘密、全文或私钥。

## 验收标准
| ID | 可观察结果 | 上游映射 |
|---|---|---|
| D-AC1 | 默认关闭不读新表、不调 resolver/provider/搜索；旧公开输出、v1 hashes、shadow 反向引用回归通过 | R1/R6；RA1/RA6/RA10 |
| D-AC2 | 实际内部计划服务依次完成 demand→selection/gap→既有模型 transport 修订→新草案重验→持久 binding；测试替身与真实 provider 证据分开 | R1；RA16 |
| D-AC3 | 源 handle 虚构、错 user/session/node/goal、草案变更、旧回调、旧 selection 冻结新稿被拒绝；合法 successor 有可追溯关联 | R2；RA16 |
| D-AC4 | 合格资料复用；existing_only 新增发现调用为0；空库/入口登记/过期/用途或版本不符返回缺口；部分ready受依赖限制且保留全部目标 | R3；RA8/RA12/RA16 |
| D-AC5 | exact corpus/doc/chunk/revision/用途/准入/授权摘要一致，跨用途或整页扩大获审摘录被拒绝；评分要求 exact claim 和可信验证，缺 resolver 默认拒绝 | R4；RA13/RA14/RA15 |
| D-AC6 | PG 双连接证明撤权先提交则冻结/发布失败；fence先锁定则撤权等待；模拟publication+materialization与receipt同事务全回滚，无自开连接/提交 | R5；RA3/RA4/RA7接口子集 |
| D-AC7 | selection与binding幂等重放、冲突、并发CAS、重启后读取可验；持久feedback→目标run唯一关联重启后可验，同稿同节点用途不能换重试键重复冻结异证据；新schema bootstrap两次；reset/delete分别验证，其他用户及共享corpus不变 | R2/R6；RA4/RA6 |
| D-AC8 | 验收逐项区分offline、隔离PG、当前真实来源、真实provider、公开consumer、E题库端到端；真实联网/API依项目持续授权和用户费用监控执行；公开consumer与E发布仍需独立许可 | R5/R6；RA10/RA11边界 |

## 非目标与范围限制
- 不新增审核服务、搜索账户/原生联网fallback，不擅自增加预算或修改旧C回执。公开资料获取与已配置真实API现获项目持续授权；不另造抓取系统，需复用受控入口及新有效grant。
- 不新增管理 UI、不改变公开 confirm 语义、不为六生态发布课程、不把 default-off 改为默认启用。
- 不接管题库 P5/P7/P8 等所有入口、真实 item 供题或 E 全链验收，不重定义 Gate/学习完成。
- 不新增 corpus/document/active pointer authority，不将 phase-I fixture 当真实授权来源。
- 不擅自修改共享脏树、保护原型或 commit/push/deploy；C 当前隔离库 guard 保留。

## 规划状态与残余前置
用户拥有的 D 范围取自已确认父规划，无新增未决产品问题。技术方案见 design.md，步骤与验证见 implement.md。真实当前来源和可信生产 claim/执行适配器未具备，本轮内部合同、拒绝路径及隔离注入验证不冒充 live 可用。用户随后已明确批准实施，实际结果以 research/implementation-verification.md 为准。

## 2026-09-27 项目运行授权更新
用户已批准开发期间持续联网/真实API使用，跨任务累计300元、240元提醒、免费搜索策略不变；唯一政策为 `docs/setup/project-external-resource-policy.md`。此批准是外部资源授权，不是D实施启动或生产发布批准。范围内后续不再逐次申请；由用户监控账单，不以先建设统一计费系统阻塞调用；不宣称程序硬封顶或自动预警。D隔离/兼容验收不变；真实模型与当前来源验证可在技术前置满足后单列证据，不再一概视为缺用户联网许可。

2026-09-27 费用策略补充：侧会话转达用户选择人工监控供应商账单；该政策取代本稿历史“先实现自动费用预留才能调用”的限制，300元总额与其他授权边界不变。
