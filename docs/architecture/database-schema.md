# Aearn 数据库 Schema 与持久化契约

## 2026-10-27：SQL迁移生命周期与受支持路径

### 候选、冻结与不可执行草案

`app/db/schema/__init__.py` 的 manifest 仍是唯一SQL顺序/分类入口；catalog metadata用于实际对象比较，不是第二份可执行schema。生命周期和目标安装状态分开：某片段在一个持久环境安装或被外部协议pin后冻结，不表示每个数据库都已安装它。当前legacy163项和非B1d前向4项已有安装/冻结事实，531仍是不可执行草案，当前没有自由候选；目录未知文件不能静默执行。

只有**已确认未在持久环境安装、没有外部依赖/协议pin、没有冻结承诺**的候选可原地修正；缺任一事实都不能默认可编辑。仅登记、审查或完整ROLLBACK演练不构成安装冻结。同一功能在持久安装前完成实际消费者、动态权限、约束/恢复和必要拒绝路径的闭合，候选小修复仍使用该候选，不逐次加编号。

首次持久COMMIT、外部pin或明确冻结承诺任一发生即冻结；保留数据、被后继工作依赖的TEST也属于持久环境。COMMIT未知时先只读对账，不能将其当未安装候选改写；已冻结SQL不修改/删除/重编号，必要修正新增明确前向版本。纯库存入口不读取配置或DB；它不提供自动历史改写、全库迁移账本或编辑授权。

### 支持矩阵

| 目标状态 | 支持的操作 | 不做什么 |
| --- | --- | --- |
| 三个具名目标已是最新`COMPLETE` | 正常只读检查；重复candidate/install/upgrade为no-op | 不重复DDL、seed/import，不更改旧用户/任务 |
| 具名目标具有完整匹配BASE、尚未安装该子系统 | 固定计划candidate全回滚，再显式install；validation另需storage purpose | 不是空数据库初始化；不以少建几张表解锁 |
| 精确已安装599前缀（validation须已有完整600用途对象） | 只读计划，维护candidate/install仅补601→602 | 不重放599/600，不开放任意PARTIAL恢复 |
| 精确已安装601前缀（validation同上） | 仅补602 | 不按最大编号猜版本，不忽略列ACL或函数漂移 |
| 仅缺一个ACL、逆序组合、未知对象漂移、缺失validation用途对象 | 拒绝；定位具体差异，另审必要前向修复 | 不自动补齐/删对象/覆盖旧数据 |
| 空数据库、任意新库名、未知历史legacy库 | 当前没有从空库到此BASE/完整runtime的已审通用provisioning路径 | 不用163项历史重放或截取前若干SQL冒充可用初始化 |

本合同当前只支持`postgres`、`aearn_completion_b_test_20261026`和`aearn_completion_b_validation_20261027`，目标名/OID/角色/purpose仍由原合同核验。此前Main从可追溯schema-only基础恢复具名域，是一次具名准备证据，不是任意空库初始化器；本轮不重建现库或迁移B1d历史数据。

### 启动与有限升级

正常CLI和受管`start-dev.ps1`只做readiness，缺失/未知selector拒绝，不退回legacy DDL/seed；`-SkipBootstrap`也不绕过只读检查。API/worker自身入口仍按原共同readiness核验。历史显式legacy维护/测试Python API不作为正常启动或当前空库支持路线，本轮不执行它。

已知升级仅从最新metadata移除601/602确切runtime SELECT delta构造前置，其他14类目录原样精确比较，TABLE/COLUMN ACL和开发13对CHECK表示均保留。只读计划不代表业务READY，旧前缀必须维护升级到最新后才能启动。candidate全TOP ROLLBACK；正式操作要求OID和维护确认，取原schema lock/BASE关系锁后fresh重查，只执行缺失的有限片段；COMMIT未知不自动重试，已ack不能被后续读回/清理错误抹掉。完整操作命令见[开发环境](../setup/development-environment.md#具名非b1d数据库合同)。

### 数据库保证与运行策略

身份/复合FK、唯一后继/单active、owner/generation、状态迁移及UNKNOWN不重派由数据库约束/trigger守护；防重复业务消费仍需原receipt owner。先保存结果、提交后再接收是跨层协议：Lesson另以SQL事务ID拒绝同事务接收；Tutor由数据库状态/owner围栏和Python短事务调用顺序共同实现，不能说SQL596独立保证了跨事务提交。

输出预留、请求等待、上下文组织/展示等一般由运行策略负责；但已经写进v1 receiver和持久依赖的2400/8/16/60、Lesson600+60期限等不能只放宽Settings。当前Lesson consumer仅接受12000/600，repository固定600/660；12000不是SQL597 token CHECK，Settings表面接受更宽值也不表示全链路支持调参，非默认会显式拒绝。参数看似timeout不等于无安全/权限含义；只有实际需要且证明不是硬边界时才调整分层，改变已安装合同须明确新版本前向SQL和consumer一致验证。本轮核查未证明有必须调整数值/receiver的必要，不为“可配置”主动放松，不新增业务权限或SQL603。

### 本轮验证与未支持路线

最终五个直接CPU文件274项、8文件Ruff/mypy、独立CODE和pwsh parser通过。22:32固定隔离validation域内实际验证599补601/602、601补602及部分ACL拒绝，三个TOP全部回滚并独立读回全目录/原记录计数不变；22:38三个现有目标均为最新602、空计划、candidate升级noop及runtime登录COMPLETE。22:40新进程从实际开发配置加载completion=true并完整只读检查。没有修改实际配置或新增持久DDL提交、真实模型调用。

这些结果不证明空库provisioning、任意旧库/任意PARTIAL、历史163整链或全应用E2E已完成。本轮新controller的changed正式COMMIT/readback故障路径为CPU/CODE证据，真实SQL分支为隔离回滚证据；原已安装601/602的COMMIT/readback记录保留复用，不重复付费业务或安装。支持范围见[支持矩阵](#支持矩阵)，候选回滚、正式COMMIT及未知提交处理见[启动与有限升级](#启动与有限升级)。

## 2026-10-27：具名非B1d首次安装与只读启动合同

`completion_non_b1d_v1` 是已有基础schema、但从未安装item-supply子系统的具名初装合同，不支持任意空库或历史中间态。实现入口仍归 `app.db.bootstrap`，普通运行前检查为 `app.db.completion_baseline.ensure_startup_contract(entrypoint=...)`；静态目录在 `completion_baseline_contract.py`，无导入时DB IO。

- `postgres` 与 `aearn_completion_b_test_20261026` 使用固定599→601→602初装计划、`runtime-purpose`；另一个具名 `aearn_completion_b_validation_20261027` 使用599→601→602→600、`storage-validation-purpose`。旧B1d库不适用，531仍是不可执行草案。三个目标已安装SQL≤602冻结，不能通过重放初装计划修复既有目标。
- schema角色固定NOLOGIN；runtime和verifier是互不继承的独立非特权LOGIN。普通用户birth、origin capture、cutover及export/reset/delete仍由正式owner执行；P2/P7生成、质量、发布与计费业务不因安装自动获权。600的有限合成存储图只能由独立verifier在固定验证域签发，不能成为真实来源/质量/发布成功。
- 目录精确覆盖表、列、FK/CHECK、索引、触发器、函数正文/owner/ACL/search_path、表/列ACL、schema、序列、角色与membership。BASE和post都以同一显式catalog search_path读取，保留PG原始表达式。仅开发目标的13个已核旧CHECK有精确成对表示，不对未知差异做字符串归一化。
- 安装时先维护静默，再取schema advisory lock与原基础关系锁，并在锁内重新判断：`ABSENT`才执行固定计划；`COMPLETE`只读no-op；`PARTIAL_OR_UNKNOWN`拒绝。正式候选始终ROLLBACK，安装显式COMMIT；未知COMMIT只能只读核对，不自动重放。新合同不运行旧seed/import或旧整事务重试。
- 显式 `AEARN_DATABASE_CONTRACT=completion_non_b1d_v1` 下，普通bootstrap与API、普通/Codex worker、beat、独立验收operator只做完整启动检查；`-SkipBootstrap`和自定义Celery loader不能绕过。验证域不能启动实际应用；专用角色/验证域DSN即使漏selector也拒绝落入legacy路径。仅显式legacy维护/测试Python API保留历史调用兼容；正常CLI和受管dev缺selector一律拒绝，不启动历史DDL/seed。

2026-10-27 10:28+08：三个具名目标已分别安装并独立判为`COMPLETE`；实际原安装与后续601/602差量记录分开保存。601只补actual-D库存读取的三张RAG表SELECT；602只补原规划resolver读取的`language_courses`、`language_course_intent_tags`、`tutor_learning_intents`三表SELECT，并把三表及两个既有coverage guard闭包纳入BASE精确目录，不新建或改写这些对象，不做课程seed/import。三库602候选均全回滚、前置目录和原数据计数保持，随后单602安装COMMIT/独立读回；验证域真实runtime登录的完整规划准备通过并全回滚。最终172项目录/loader/manifest CPU、Ruff/mypy通过；8个真实角色存储场景使用此前7+1证据，不重复刷矩阵。

`CATALOG_CANONICALIZED=True`仍只说明目录可比较，不单独证明安装或业务READY。API、普通/Codex worker及beat已有受限新进程启动证据并停止；HTTP main03与sidecar新r2分别实际通过。10:36开发completion设为true，新验证进程从实际`.env`加载runtime登录与selector并完整只读判COMPLETE；这不表示原API/worker仍在运行，也不是Desktop/HTTP-SSE E2E。操作入口见[本地开发环境](../setup/development-environment.md#4-bootstrap启动与停止)。

12:13补充真实Lesson闭环：原runtime TEST/专用runtime登录经原user/cutover/track/Lesson prepare正常准备新合成scope，默认真实作者完成两个请求；SQL597两阶段结果独立持久化并accepted，personalized精确引用standard阶段，原最终事务提交两稿/唯一assignment/run完成，独立公开投影一致。本轮没有新增或重放DDL、课程seed、来源GET或validation receiver；SQL≤602保持冻结。批准B切片按此及既有分层证据收口，不扩大为P8或应用E2E。

## 2026-10-26：完成驱动的三个持久化合同（596–598已安装冻结，真实调用另验）

本节对应已批准的独立 B 组增量，不改变历史 P7/P8 接收状态。候选片段为 `596_tutor_completion_execution.sql`、`597_lesson_completion_stages.sql`、`598_tutor_completion_sidecar_bindings.sql`，SQL≤595 保持冻结；新合同默认关闭，仅新显式运行可进入，不转换旧行或重开旧终态。

- `tutor_run_execution_batches` 保存同一逻辑 Tutor run 的有界资源批次、唯一前驱/后继、当前 owner/generation 和累计计量。新批次重新取得执行资格，不清零逻辑工作、模型调用或 HTTP 历史。
- `tutor_run_step_attempts` 保存派发前已提交的步骤意图、精确依赖、实际私有 typed 结果与独立业务接受状态；`(id, run_id, user_id, conversation_id)` 是 sidecar 引用的复合身份。结果记录不等于接受；恢复须经当前权限与原业务校验，UNKNOWN 不能重新派发。
- `tutor_lesson_authoring_stage_attempts` 只承载标准稿和个性化两个阶段，保存完整依赖、候选、质量反馈与精确适用范围。合格标准稿可在模型调用前复用，个性化接续不提前发布 assignment，最终仍经原发布事务。

既有 `tutor_lesson_authoring_runs` 追加可空 `completion_contract_version`，新合同为 `lesson_completion_v1`；NULL 保留 legacy 生命周期。既有 `tutor_lesson_source_snapshots` 追加 `evidence_schema_version` 与 `evidence_units_json`：完整必要依据供生成读取，1200 字符内的 excerpt 仍只作展示；旧来源身份与 hash 不改，来源 current/retention 不延长。

既有 `tutor_run_runtime_bindings` 追加可空 `step_attempt_id`，不新增第四张表。旧运行保留单 binding，新运行每步骤唯一且同 run 最多一个 active binding；内部 turn 的终态不直接终结未完成的业务。审计引用和 immutable guard 保留，不能为清理而绕过 FK。

用户摘要、导出和 cutover 仅按实际已安装关系查询当前用户计数；查询失败不视为未安装或零条。导出不包含完整依据、请求、候选或 provider 结果。Lesson 阶段清理由现有用户 purge 能力约束并先于其父记录，普通课程 reset 不额外清除仍随 Tutor conversation 保留的执行审计。

验收分为源码/CPU、独立CODE、隔离库完整候选、开发库安装回读、配置激活和普通HTTP/sidecar实测。已完成具名CODE、179项整合CPU、14个真实PG接收器用例；补充单一注册Python文档后，新增两个Lesson领域owner/恢复/最终发布PG用例通过（fixed author，不是真实模型）。2026-10-26 22:52+08，596–598及同一保存文档在开发库原子提交并独立回读：23chunks、19admissible，未二次GET；这三片自此冻结。真实入口在原clean-start检查发现dev/TEST均缺66个既有P2/P7库存关系，尚未进入provider，completion开关已恢复关闭。定义定位涉及440/450/460/470/481/485/495/496/501/502/521/523/524/551，但这不是已审核执行清单，不能直接重放冻结片段或把缺表当0。

2026-10-27补充基线对齐授权后：manifest保留163项active原顺序，并将531精确声明为保留且不可执行draft；所有未知文件、缺失声明、重复或active/draft重叠仍拒绝，531不进入load/apply，SQL≤598未改。聚焦manifest CPU14项通过。主代理在原隔离库以只读事务提交原523/524文本，均在原首个库名门禁返回23514/B1d only并完整回滚，独立读回未变。18个来源/79表仅为66关系的结构依赖线索，不批准抽取表定义以绕过scope或丢失owner/immutable/epoch约束。当前未提交基线DDL；需完整的非B1d前向初装合同审查后，才可继续开发库对齐与两通道验收。

## 2026-10-16：C19 handle域修复563已安装，质量准备回滚通过，writer已过期

原440 private version的opaque storage handle与version UUID分别生成，不能拿它与native canonical handle作等式。563仅精确前向修quality、publication insert/current、continuation terminal与560 readiness五个prosrc，0新增对象；原version行与generic storage不变，native域始终使用已验证actual version UUID派生值。13:17选定安装及catalog/history保全通过，**所有已安装SQL≤563冻结；后续必要修复仅新增≥564**。

新的quality-only flat cap从已提交C18 B、实际output/bridge/completion/artifact/checkpoint和同current writer重新签发，不恢复旧persistence cap或Prepared、不重做A/B。原质量prepare完整回滚PASS，HTTP0。独立最终CODE已PASS，包括在原facts最后SOURCE/accounting复核后的新DB clock检查完整7×timeout+15秒余量；不足时在_started/blind/HTTP前拒绝，普通PRIVATE不扩此规则。

13:28:46只剩565.7316秒，低于715秒下界，故Main未提交C、未调用质量模型。13:48:04只读确认本次C18 writer已于13:38:12自然到期：output/原known费用/bridge/completion/generation Artifact各1，quality/reservation/publication各0，547六项各1，其他非空闲会话0。历史terminal仍返回artifact，不等于live authority或published。账本163、历史UNKNOWN/null不变；作者HTTP0、质量HTTP0。PRIVATE独立质量、增强、真实Tutor及P7仍未完成，后续仅质量新phase/window需另行明确授权与设计；不延长旧lease。完整当前交接见原任务research/p7-c18-c19-result-handoff-20261016.md。


## 2026-10-16：C18 指定输出的新持久化／质量阶段562已安装

用户批准对560 output `f4519c66-4130-4e34-b053-64dba6214dcb` 签发一次原owner新阶段及独立新窗口；作者与原作者重结算均为0。历史request/profile/result/source/receipt/known费用不变，新writer/profile/accounting/phase独立。562新增8函数、3trigger，仅精确前向修原artifact接收器、558 terminal及560 readiness的三个prosrc；保留原OID/owner/ACL和非目标目录。A唯一binding与B实际artifact/checkpoint/completion分别deferred闭合，A/B/C使用完整服务器TOP标记；历史完成事实不冒充current权限。

联合DESIGN、CODE及增量CODE通过。Main最终selected compile/replay/catalog/history回滚、原A准备／same-TOP拒绝／无残留回滚均PASS；12:34北京时间选定安装562，证据 `.runtime/p7-private-current-20261014/private-persistence-phase-schema-20261016T043458220158Z/result-private.json`。**所有已安装SQL≤562冻结；后续必要修复只能新增≥563，不重放旧片。** A于12:39:38、B于12:42:19实际提交，原输出已成为Artifact `c8057dcb-a110-45fa-ab0b-46cd91c99191`；C质量准备随后因原524把存储opaque handle与native canonical version-ID handle作等式比较而拒绝，完整回滚且HTTP0。原terminal实际读回artifact，不是published。质量/增强/P7仍未通过；只可在当前writer有效时按已批准的精确committed-completion新owner分支重新签质量权限，不重做A/B或修改旧行。

实际探针中修复了新A多余savepoint与原551的冲突、新SQL把TOP起始时间当实时DB clock的比较、以及accounting projection的batch_id误读。没有修改450/551或延长期限。原PUBLIC审核/547/关系保留不重跑，历史UNKNOWN/null不变；真实PRIVATE质量、增强与Tutor仍需各自证据。最新合同与状态见原任务C18授权、Python/SQL wire及独立检查报告；下列C17/C16段落保留其历史时态。

## 2026-10-16：C16真实输出已留存，C17来源hash域错配已定位

新PRIVATE作者真实HTTP1返回staged，known settlement及完整560 output f4519c66-4130-4e34-b053-64dba6214dcb均独立提交；账本163条、历史UNKNOWN/null不变。原Artifact事务随后在559 source identity守卫拒绝，artifact/quality/publication仍0。原进程已退出，但完整结果已留存在DB，**不得再次付作者或还原旧sender registry**。

Main逐项原current/全回滚与READONLY诊断确认：身份/hash、slot/mapping/goal和全部来源当前条件都通过；实际错误是524 private_native_source_current将完整ClaimEvidenceReceipt hash错比为SignedSourceAssessment verification hash。原具体reader与DB权威列重建一致证明两个hash各自在正确域匹配。来源窄修561已独立CODE通过，05:19:13原fresh SOURCE的source_current/goal_current全回滚正例及四个hash/handle/epoch负例通过；05:19:56选择安装并读回成功，已安装≤561冻结。固定DB output的独立persist-only/quality handoff仍在实现与独立审阅阶段，尚无Artifact。原05:27:49+08 writer截止不延长，到期/质量窗口不足即停止；PRIVATE质量、增强、真实Tutor及P7仍未完成。详见原任务research/p7-c17-private-source-claim-hash-design-20261016.md与p7-c17-durable-output-persistence-continuation-design-20261016.md。

## 2026-10-16：C16 PRIVATE输出留存560已安装，固定技术终结与新准备验收通过

560新增8个封闭函数与2个trigger，仅精确前向修改558 predecessor/terminal的body；原OID/owner/ACL及其余catalog与既有行保持。新原live结果返回前由service封存完整context/result；费用先写、完整输出在同caller TOP的savepoint追加，capture失败不回滚费用；artifact必须另TOP消费匹配的已提交output。原SQL生成并校验完整TOP标记，同TOP释放savepoint不能冒充提交。旧C14 candidate明确禁止回填，known/unknown/null语义保留。

独立CODE通过；直接Python46项、新SQL10项及另一个旧preIO case1项通过，Ruff/新文件scoped mypy通过，7项既有union-attr基线未扩修。Main selected560 compile/replay/history rollback通过，04:21安装提交，**已安装SQL≤560全部冻结**。原固定gap完整rollback及同TOP精确拒绝通过；04:22:47仅提交原issuer精确gap＋必要current-source origin两行，旧control/once/settlement/产物不变。04:25:56新TOP原后继prepare完整rollback的job/control/journal/settlement/artifact/quality/pub残留全0，547六项各1、其他非空闲0、HTTP0、ledger162未变。

现开始一个新有界作者阶段，尚无本次新输出capture或独立质量验收结论。技术gap只记录已收费、自然过期、无持久输出，不把旧staged改为provider失败，不恢复旧cap/once或导入旧文件。PRIVATE增强/真实Tutor/P7整体仍未完成。详情及证据路径见原任务research/p7-private-generation-durability-and-gap-design-20261016.md。

## 2026-10-16：C15 PRIVATE live actor修复559已安装；原作者输出未持久

C14真实新作者返回staged、HTTP1，known结算独立提交（input12916/output2082/total14998、费用null），账本162条。原generation INSERT被524仅允许P6 actor的条件拒绝；artifact/质量/发布均无新增。结算hash只绑定provider元数据，不绑定完整生成内容，原进程已退出，本地DATA不得恢复为原能力或回填。

559仅前向修原pipeline artifact/receipt trigger的PRIVATE live原身份分支，完整namespace/active plan/task/root/phase/lease/source/typed receipt及末端时钟保留。独立CODE和Main selected compile/replay/history rollback通过，03:29+08安装提交；原OID/owner/ACL/其余catalog、既有行与547六项各1不变，HTTP0。已安装SQL≤559冻结，不重放旧524/558或full bootstrap。未来真实generation/receipt正向接收仍待新合法阶段。

C16已独立DESIGN通过、正在实现：仅对固定C14已收费、自然lease过期且无完整持久输出的事实追加technical disposition，不改写staged为provider失败、不恢复旧once；未来原活结果返回前封存，settlement后同TOP savepoint留存完整output、费用始终保留，artifact另TOP核已提交output。具体见原任务research/p7-private-generation-durability-and-gap-design-20261016.md。PRIVATE独立质量/增强/真实Tutor及P7整体未完成；无Git或公开发布。

## 2026-10-16：C14 PRIVATE失败前向接续558已安装，质量链开始执行

用户明确批准P7三阶段统一收口及新PRIVATE作者次数无限制；不恢复旧555 once或旧失败进程能力。558新增10个具体接收器和2个trigger，尝试key严格由同scope已提交真实前驱failure确定；原唯一后继、先提交准备/consume、原IDLE发送、独立结算、fresh SOURCE/lease/accounting及成功artifact后禁止再初始author均保留。仅前向修改原555辅助trigger函数的精确body，向新完整接收器分派，原OID/owner/ACL/非body属性保持；旧SQL源≤557未改，≤558现全部冻结。

Main selected compile/replay/历史行+非目标catalog保全/rollback通过，原service准备完整回滚与错误前驱/未提交consume拒绝通过；02:03:10独立读回该probe全部残留0、547六项各1。selected558随后安装并提交后读回成功。当前才进入原新作者与独立质量阶段，不据schema安装声明PRIVATE质量、增强或真实Tutor通过。新作者human次数不限但原单阶段有界；旧UNKNOWN/费用null和C13 PUBLIC后端PASS保持。详见原任务research/p7-private-author-continuation-design-20261016.md。

## 2026-10-16：C13原Artifact后端无模型完整回滚验收通过

仅修Main验收脚本的programmatic教学输入（2个不同teaching_moves及对应消息），没有改产品SQL、CHECK或TTL。独立CODE及离线实际AST/原DTO验证后，Main一次diagnostic-off原链运行返回completed；原最终SET CONSTRAINTS ALL IMMEDIATE及current_handoff退出通过。事务内读回action1、native consumer create1、529 clearance4（advertise×2、prepare、create）、knowledge_check Artifact1，PUBLIC_scope_cleared=true。证据.runtime/p7-private-current-20261014/fallback-artifact-20261015T162508103303Z/result-private.json。

00:27:19+08只读确认本run/artifact/action/consumer/529全回滚为0，547六项仍各1、其他非空闲会话0；HTTP/模型0、ledger161字节不变。SQL≤557冻结，新pack120及独立30秒保持，没有恢复作者许可、Git提交或公开发布。原PUBLIC整包fallback到Artifact创建的后端programmatic DATA路径现已验收；PRIVATE独立质量链/增强、真实Tutor侧质量及P7整体仍未完成。下节C12失败是保留的先前阶段记录，已由本次合法输入运行解决，不应据其旧状态继续重跑consumer修复。

## 2026-10-16：C12 consumer PUBLIC 合同557已安装，完整Artifact验收仍未通过

549的原consumer组13错误要求严格LearningItemPublicV1中不存在的public_json.visibility。557只将该JOIN谓词改为公内容列/JSON schema均learning_item_public_v1，且原immutable publication proof的lease.visibility=public、owner_id/owner_epoch为显式JSON null；缺键不默认public。PUBLIC身份来自原proof lease命名空间，不来自内容正文。原version/public_hash外键、proof/current-source/selected/member/actor/epoch/同TOP/postwait及所有consumer/Artifact围栏保持；新签发pack120及独立30秒政策不变。

独立DESIGN/CODE、19项focused测试、Ruff/scoped mypy通过。Main00:01:48隔离PG selected557真实编译/同片replay/原行与非目标catalog保全/回滚通过，00:02:12提交安装后读回通过；原consumer OID/owner/ACL/全部非body属性保持。原2practice新JOIN通过，9个错误schema/缺键/private/非空owner等直接谓词负例拒绝；非整个current证明。证据原任务research/p7-consumer-public-contract-fix-design-20261015.md；runtime consumer-public-contract-20261015T160147406440Z与20261015T160211565009Z。≤557全部冻结，旧549不得重放，不运行full bootstrap或激活531。

其后唯一无插桩、无模型原Artifact全链运行已越过consumer及事务内materializer.create返回，失败在action receipt INSERT的chk_tutor_teaching_action_receipts_version_shape：Main programmatic DATA仅1个micro_transfer，而当前合同及实际CHECK要求2..4。不是新的consumer/TTL失败，不放宽原合同、不自动重跑。完整terminal/最终约束验收尚未通过，无持久Artifact，P7未完成。证据.runtime/p7-private-current-20261014/fallback-artifact-20261015T160256682789Z/result-private.json；00:05:14只读确认本run/artifact/action/consumer/529均0、原547六项各1、其他非空闲0。HTTP0、账本161字节不变、作者0，无Git/公开发布。下一步先修Main合法验收DATA，再进行新一次原链完整回滚，不需为该输入错误新增SQL。

## 2026-10-14：550已安装、原四角色关系已commit；整包current受30秒曝光时序阻塞

550仅修原native relation receiver两处query-local c别名与PLpgSQL变量歧义，原root/phase/lease/author separation/request hash等条件未改。实际compile/replay与完整原prepare rollback通过后selected安装，冻结文件SHA f63b7014e5818dc5c6e126ca9ed3ef59be85e37eee4213378369f9bf3483a80a，receiver body70194b777ae1860df750c87e62b278360601842d98c6c9a4011defeba02dbb51，pipeline及producer两处pin同步；原OID/owner/ACL等保全。schema manifest550已登记，<=549冻结。

Main同一任务/selected5的新原phase 032bac08-b091-47dd-bed5-2c99b03a65da真实四角色完成并commit relation_ready，原receipt e1578bca-7835-4884-b8d5-2f45d8194d5c及4ProviderRun已DB回读。4实际HTTP，ledger158→159，旧事件/UNKNOWN保留；runtime aggregate UNKNOWN、金额null。证据 .runtime/p7-current-receivers-20261014/relation-live-20261014T052949500329Z/result-private.json。禁止重付/重生成该关系；关系ready不等整包ready。

其后原get_status→resolve_pack→_exposure真实SQL502拒绝。Main新原snapshot/resolve_pack/savepoint回滚诊断 exposure-diagnose-20261014T063910445789Z：checked14:39:49.867、valid14:40:19.867、真正检查14:42:48.651，179秒后仅time_current=false；水位/计数/原hooks/birth/inbox全true。0HTTP/provider，无关系replay。原snapshot与candidate期限30秒不延，不用旧snapshot；必要原owner TOP生命周期重排处于设计中，源/epoch/退役/曝光变化及原消费门禁独立保留。PRIVATE、原Artifact消费与P7尚未完成。


## 2026-10-14：whole-pack原current source及549已验收、安装

原owner显式签发同任务current-source进程能力并经NativeType严格安装；旧PUBLIC proof/source refs、实际published_at、mapping与selected5均不修改。新旧材料/目标/请求语义完全一致，各自签名授权policy/gen/source预算/root/delegation/expiry分别核验；新C不是新模型钱包。549仅向既有PRIVATE journal写显式current origin DATA，原consumer create/consume与PRIVATE base原SQL source fence校验同actor/epoch/mapping/task/原proof/新C及真实provenance，默认旧分支仍严格。origin或文件中的UUID不能恢复能力，provider/relation/exposure/PRIVATE/delivery各门禁独立。

Main正向source-rehearsal-20261014T020236843430Z回滚：原mapping、selected5 NativeType与SQL source接收器均current；原PUBLIC状态仍preparing/relation_required/qualified_slots5。否决source-negative-20261014T021800025454Z：foreign actor/wrong epoch/expired origin均拒绝。install549-20261014T022354186834Z selected安装已commit并注册manifest，冻结SHA a283f28331cc9c1d048ee9a1ae8066ff71ea5e9fd65124f80800a8b6f39f94f2；无需548，531未启用，<=547未改，旧历史/ledger保全，新增项目provider/HTTP为0。完整关系4角色、ready、PRIVATE及原Artifact consumer仍未验收，P7_complete=false。下节“source549实施中”是早先同日历史检查点，当前以本节为准。


## 2026-10-14：547历史DATA的原NativeType current读取已修复（无548迁移）

原reader现显式核验547新admission与历史validation/producer/review的分离 origin，不全局放松旧JOIN/profile规则，不恢复旧Issued/lease/scorer注册表。PG prep.created_at是TOP now而非实际lease bind时间，历史校验分别保留audit顺序和stage在原bind/截止内的发行边界。Main原新child current全回滚通过：bank_current/native_current=true、547六项各1、schema/ledger保全、HTTP/provider0；证据.runtime/p7-current-receivers-20261014/probe-20261014T012034658233Z/result-private.json，独立history检查PASS。无需548；547及更早冻结，531未启用。

这只修复最新child历史数据读取；四旧发布版本当前source_unavailable与普通mapping source_or_claim_stale仍准确拒绝。新whole-pack source purpose设计经独立审阅补入549 explicit origin/原consumer与PRIVATEbase SQL source接收器后PASS，产品/DDL仍实施中，未据此声明current整包/PRIVATE/consumer或P7完成。

## 2026-10-14：547 已提交质量回执的零 provider 准入接续（已安装）

`547_learning_item_committed_child_admission_v1.sql` 已在原隔离数据库通过真实有数据 prepare、完整原 admission evaluation（eligible_internal）、重复发行拒绝、DDL 重放及全回滚，并选择性安装。SQL SHA-256 为 `3bc3ec3e0c547a3249dfa25816c50824f9c100c706332ef2411de33c5bb5c7cc`；546及更早已安装片保持不变，531未启用。

新模式仅覆盖原 PUBLIC task 9378a05f-b33e-5fc9-9bd7-6f073c2e6c8c 的已提交 child 4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3 和确切 validation/blind/六审/recheck 回执。复用现有 shared persistent journal 的 committed_admission DATA，不新建表；新原 owner 能力固定 once 身份，独立当前控制/15分钟期限与当前 PRIVATE 来源映射校验。历史 producer/review 的租约只核验当时发行合法性，不延长、不改写；旧 phase UNKNOWN、controlled hold及原费用 UNKNOWN均保留。新 admission role禁止创建 provider reservation，不能重跑作者/调查/审核。normal v3、facts/evaluation、原 native import/internal-publication及同槽 qualified 仍逐项接收，不由 lineage 或新版本号单独放行。

原 admission caller同步修正盲解协议核验：V2仍legacy-only；V3仅识别原已登记协议并重建确切 input hash/prompt。未知版本、错输入、跨policy、角色或风险缺口仍拒绝。没有手填 eligible、恢复旧 scorer/Prepared/review注册表或用本地文件签发权限。

唯一新admission action已实际完成，normal、facts、evaluation、import、native internal-publication、same-slot qualified回读各1，published version为8ba4ca51-e8f4-540a-b52a-eaec8a0a6764。提交证据为`.runtime/p7-committed-admission-20261014/commit-20261013T183819697920Z/result-private.json`及同目录`committed-finalization-private.json`：HTTP/provider0、账本158条原样、旧历史保留。单child成功不等于完整P7或公开发布；旧复核回执的blockers_discharged=false及四条历史unsupported争议不因此改写。随后原current读回确认两个剩余接收阻断：普通映射pending/source_or_claim_stale使get_status拒绝，修订专用来源successor不能升级为整包许可；NativeTypeEvidenceOwner原validation/facts同job/profile JOIN排除新547合法分离模式，报native_exact_original_publication_required。两个0HTTP回滚探针见同目录post-admission-current-pack-private.json及post-publication-current-receivers-private.json，修复尚未实施，不放宽旧SQL。验收：`.runtime/p7-committed-admission-20261014/rehearsal-20261013T183316281657Z/result-private.json`；安装：同目录 `install-20261013T183808319893Z/result-private.json`。两者HTTP/provider为0且账本未变。

## 2026-10-14：546 已提交修订子项的显式 fresh recheck

546_learning_item_committed_revision_recheck_v2.sql 已通过真实PG编译/重放及原有数据prepare、validation prepare、重复拒绝全事务回滚，并于北京时间2026-10-14选择性安装。追加片不修改已安装迁移，531仍未启用；无新表、列或索引。新增4个内部检查函数，精确替换510复核、522 normal分派、persistent journal与原491 adoption共4个receiver，并只扩510 preparation/receipt两处schema-version CHECK；新函数无PUBLIC执行权限。旧行、函数身份/属性、原v1分支及既有唯一性/FK保留。

新v2把历史producer与当前review operation分开：541 output/settlement、原artifact/checkpoint/lineage保持不可变；新phase与491 adoption绑定同root和child。精确committed-child版本DATA先登记，再adoption/validation，避免旧journal必须先有validation的循环。历史generation-policy仍校验原作者request/profile，不覆盖为新审核profile。normal v2经原matcher、facts、import与publication接收链，保留producer和operation双重controlled检查；旧争议未解除。

实际准备/安装证据在 .runtime/p7-post-revision-20261013/。随后真实执行已提交machine_verified validation、独立盲解、六角色全approved和v2复核receipt；normal side/facts仍为0，原phase保留outcome_unknown，不改写为成功或重新付费审核。准入、发布及完整P7未通过。精确异常未保留，后续只应从已提交回执定位和设计未花费准入接续。


## 2026-10-13：545已安装，原修订持久化链实际通过

`545_learning_item_revision_source_reference_successor.sql` 仅替换 `fresh_committed_revision_matches`、`enforce_native_revision_insert`、`persistent_registered_family_revision_matches` 三个原函数体；无新表/列/索引/grant，保留OID、owner、ACL和旧数据。原工厂仅在已核验543接续来源时生成显式v3上下文和新引用，其余父项核心、覆盖、profile与family约束保持。545没有原地改写已安装的历史迁移。

完整原组件TOP准备、作者设置、重复拒绝、DDL重放与全回滚通过后安装545。随后单次真实作者将原输出与known用量结算提交；另一进程仅从541数据库durable output恢复，提交子产物 `4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3`、checkpoint与lineage `4228be3f-a129-4c06-a531-4d69a37c1d46`。数据库回读的原输出、request、source、receipt完全一致；恢复过程无HTTP且未还原作者内存注册表。证据：`.runtime/p7-source-mapping-successor-20261013/revision-persist-20261013T142128544206Z/result-private.json` 及同目录 `committed-revision-readback-private.json`。

这完成本次修订的生成及持久化，不解除审核blocker：`admission_eligible=false`、`blockers_discharged=false`、`publication_enabled=false`。旧三条UNKNOWN及539已知结算不变；完整P7仍未通过。以下543/544安装记录保留各自当时的验收范围。

## 2026-10-13：543 来源与已确认课程接续已安装

`543_learning_item_source_mapping_successor_v1.sql` 已通过实际编译、重放、原 PUBLIC/confirmed PRIVATE 来源准备与全回滚，再选择性安装。范围仅4个新内部函数、3个原接收函数体、PRIVATE journal的1个CHECK和1个插入trigger；无新表、列或索引，旧行和原函数身份/权限保留。新函数均撤销PUBLIC执行权限。

`source_mapping_successor` 复用原PRIVATE journal及其生命周期，显式绑定原任务/root/父项/调查与新签名来源，不修改旧mapping、调查、期限或UNKNOWN。原组件的2次新source oracle、签名落库、PUBLIC C激活和PRIVATE provenance实际通过；这不等于修订、准入或发布通过。修订仍须完整无HTTP原TOP验收及实际durability→artifact/checkpoint→lineage。


## 2026-10-13：544 原来源单次接续已安装

`544_rag_registered_course_refresh_successor.sql` 独立于来源/映射接续543，仅允许已授权 python_reference gen3单次新抓取。旧来源root、grant、capture、两次历史消耗不变；新access-only root明确携带2次历史消耗，总上限3，仅新增1次dispatch。7天材料及30分钟派发上界仍由原接收函数约束。仅1个原函数体、3个CHECK、2个唯一约束→2个partial UNIQUE；函数OID/owner/ACL及所有旧行保持。实际原issuer、重复拒绝和派发INSERT已在TOP全回滚验证，随后选择性安装成功；不代表新来源证明或修订已通过。

**状态：** 当前 schema 说明，2026-09-02。
**权威来源：** `aearn/services/api/app/db/schema/__init__.py` 的显式 manifest、`aearn/services/api/app/db/schema/*.sql`、PostgreSQL bootstrap、
Tutor/LearningTrack repositories 与 schema/cutover tests。
**范围：** PostgreSQL 是 Tutor run、cutover receipt、背景队列和 learner-safe
projection 的唯一 durable authority；Desktop、Celery 和 provider 不拥有并行
状态机或迁移账本。

## 1. Bootstrap、迁移与范围原则

- 仅保留的显式legacy维护/测试Python API `bootstrap_database()` 会按 `SCHEMA_FRAGMENT_NAMES` 的原顺序执行其中登记的fragment；它不是正常CLI入口，也不是当前受支持的空库初始化路线。本轮没有执行历史整链。数字前缀只帮助阅读，执行顺序不依赖目录自然排序。正常 `python -m app.db.bootstrap` 必须选择具名非B1d合同且只读检查；缺selector拒绝。不能把599/600接到原163项后再跳过523。当前仓库没有可与该owner竞争的Alembic/Graph迁移路径。
- 该legacy API的所有fragment在同一caller-owned PostgreSQL connection和最终提交事务中执行；loader不`commit`。其transaction advisory lock及deadlock/serialization failure有界整事务重试仅为历史维护/测试兼容保留。具名非B1d初装/升级的候选、显式COMMIT、独立读回和未知提交处理按上文合同，不沿用该重放策略。
- `load_schema_text()` 只提供 manifest 组合的只读视图；仓库不维护第二份聚合 `schema.sql`。
- `tutor_*` 与 `harness_cutovers` 是当前 runtime 的核心表族。所有可公开读取的
  内容必须从 repository 的安全投影产生，不能直接把 JSONB、trace 或 provider
  数据返回到 API/SSE。
- 旧 `learning_*`、`review_*`、`notes`、`attempts`、`learning_plans` 等表仍在
  schema 中，以便服务器能够对已有本地用户做精确 inventory/delete、数据摘要、
  导出和已归档证据。它们不是当前 Desktop/Tutor runtime 的写入目标。
- 服务器不把旧记录迁移到 `tutor_*`。confirmed clean-slate cutover 删除精确
  legacy scope；rollback 只可能恢复代码，不会重建已删除历史。

## 2. 基础身份与课程表

| 表 | 当前作用 | 关键边界 |
| --- | --- | --- |
| `users` | 本地学习者 identity、显示名称、时间段、通知偏好 | `id` 是所有 user-scoped Tutor 数据的根；身份和允许的通知偏好在 cutover 中保留 |
| `language_courses`、`runtime_profiles` | 目录/环境安全 read model | 只通过课程/环境接口读取，不成为旧计划恢复入口 |
| `idempotency_records` | 历史业务的本地数据记录 | cutover 按精确 `user_id` 删除；不与 Tutor API idempotency 混用 |

## 3. Server-authoritative cutover

### `harness_cutovers`

主键是 `(user_id, cutover_version)`，当前版本为 `harness_clean_slate_v1`。

| 字段/状态 | 含义 |
| --- | --- |
| `state` | `required`、`summary_ready`、`verified`、`verification_failed`、`blocked_target_state` 或 `blocked_checkpoint_scope` |
| `summary_hash`、`summary_version`、`preview_nonce` | 服务器生成的可验证预览事实，不包含旧学习正文 |
| `confirmation_idempotency_key`、`confirmation_request_hash` | one-time confirmation 的安全重放/冲突检查 |
| `confirmed_at`、`verified_at` | 删除确认与可进入 Tutor 的时间事实 |
| `failure_code`、`failure_at` | 失败/阻塞的稳定安全码，非 raw exception |

`verified` 才允许 `/api/tutor/*` 与 verified-only 背景工作。任何预切换
`tutor_*` user-scoped row 都构成 target contamination：服务器写
`blocked_target_state`，而不是删除或迁移新数据。

### 历史 scope 与 checkpoint

服务器只删除能证明归属当前用户的 legacy 行，并对
`aearn:learning:<learning_session_id>` thread ID 逐表检查
`checkpoints`、`checkpoint_blobs`、`checkpoint_writes`。未知表/namespace、
`NULL` thread ID、未知 learning thread 或无法证明映射的记录都 fail closed。

## 4. Tutor 对话、TurnRun、公开过程与可重放事件

| 表 | 责任 | 关键不变量 |
| --- | --- | --- |
| `tutor_conversations` | user-scoped learner-visible/internal conversation 根 | `visibility` 与 `kind` 区分公开交互和内部 proactive conversation；learner conversation 的 `title` 只能保存安全模型简述，`NULL` 对外投影为“新对话”；`last_public_activity_at` 是列表排序 authority；`next_public_event_sequence` 与 `control_version` 均从 1 开始 |
| `tutor_messages` | canonical learner/Tutor public message body + bounded public thinking narration | 唯一允许存放原始 learner 文本的 Tutor 表；新 Tutor 回复保存最多 1280 字符 `public_thinking_text`，legacy `public_thinking_steps_json` 只读兼容，CHECK 禁止双表示同时非空；二者都不是 provider-native reasoning |
| `tutor_message_context_references` | learner message/run revision 的 append-only learner-safe artifact snapshot | 复合 FK 固定 user/conversation/run/message/input revision；只保存 bounded safe projection/hash，不复制 learner content、submission、hidden/private artifact 或 raw execution/provider 数据 |
| `tutor_catalog_snapshots` | reviewed Skill catalog digest snapshot | run 只能引用已持久化的 digest |
| `tutor_codex_runtime_health` | dedicated `tutor-codex` worker 的共享 readiness authority | 仅保存 bounded status/generation/version/model/provider/protocol/safe code 与 heartbeat；新 Codex admission 必须读取 fresh exact row |
| `tutor_runs` | 有限 loop / public turn 的 durable snapshot | `origin` 为 `interactive/proactive`；`runtime_kind` 在创建时冻结为 `harness_v1/codex_sidecar_v1` 且不可更新；`interaction_protocol_version` 区分 `legacy_v1/thread_turn_v2`；retry predecessor/root 与 `response_to_request_id` 通过 user+conversation scoped FK；lease、budget counter、`input_revision`、terminal outcome、`completion_reason` 和 `next_event_sequence` 都由 DB 保护；新 v2 request 来源 turn 不持久化 waiting continuation |
| `tutor_interaction_requests` | typed learner/authority blocking request 与 resolution lineage | kind/actor closed union；每 conversation partial unique pending；source/answer turn 与 answer message 复合 scope；server-owned descriptor/presentation、planning catalog、approval identity、authority scope/hash、state/version/response-or-receipt hash 受 CHECK/FK/CAS 约束 |
| `tutor_provider_attempt_receipts` | 每个实际 provider HTTP attempt 的 append-only usage 事实 | identity 为 `(run_id,input_revision,decision_iteration,attempt_index)`；复合 FK 固定 user/run/conversation scope；只保存受限 provider/model/protocol、outcome/diagnostic 和非负 token 数，不保存 prompt、response body、reasoning 文本、URL/header 或 credential |
| `tutor_conversation_runtime_threads` | conversation-scoped Codex App Server thread authority | 一个 learner conversation/runtime 至多一个 active thread；external identity immutable/private；resume/compaction 只更新时间事实 |
| `tutor_run_runtime_bindings`、`tutor_runtime_item_receipts`、`tutor_runtime_public_errors` | fresh run/turn private correlation、append-only safe receipt 与 Aearn public error | external thread/turn/item identity 不进入公共 DTO；binding/receipt 受 input/lease/Runtime generation fence；receipt 不复制 raw text |
| `tutor_runtime_text_items` | owner-scoped raw reasoning/final-answer projection | reasoning 与 final answer 分 channel；sequence/hash/state/owner/FK 受约束；commentary/summary 不写入 text projection，只有安全 final answer 关联正式 Tutor message |
| `tutor_run_public_processes` | 一条新 interactive run 对应一条 server-safe public-process projection | 只允许 `thinking/waiting_input/waiting_approval/waiting_authority/completed/interrupted/superseded/unavailable/failed`，只保留 timestamps、关联 public Tutor message 和固定 step key；不存 reasoning、provider payload、prompt、trace 或工具参数 |
| `tutor_run_public_process_steps` | append-only public-process step order | `(run_id, ordinal)` 唯一；step key/state 均有 DB + repository allowlist；公开 label 在 read projection 映射而非存自由文本 |
| `tutor_run_skill_selections` | exact Skill evidence | `(run_id, input_revision)` 唯一；保存 id/version 与 manifest/instruction/evaluation hash |
| `tutor_run_input_events` | 已接受输入的 revision/event receipt | 普通消息与 typed response/verified authority receipt 都在 fresh run 上从 revision 1 开始；legacy continuation 才可能在旧 run 增加 revision；用于 replay 与 stale-effect gate |
| `tutor_run_checkpoints` | metadata-only checkpoint | 不保存 assembled prompt、raw history 或 provider payload |
| `tutor_run_events` | run-local ordered event log | `event_sequence` 在 locked run row 上分配；SSE 只读取其安全后缀 |
| `tutor_conversation_events` | learner-safe conversation-global append-only event log | conversation row lock 分配严格递增 sequence；v2 kind 包含 bounded `turn_output`；`event_key` 幂等；turn/item reference 与 payload identity 必须一致；普通 UPDATE/DELETE 被 trigger 拒绝 |
| `tutor_turn_public_thinking_streams` | 当前 foreground Turn 的可恢复公开思考前缀 | one-row-per-run；exact user/conversation/run/revision/decision/generation/provider-attempt fence；state=`active|complete|discarded|accepted`；`active` 文本仅通过累计安全检查、仍是 provisional，`complete` 表示完整 provider decision 已验证并与 stream exact match；不保存 raw provider 数据 |
| `tutor_interactive_dispatch_jobs` | one-row-per-run durable interactive dispatch authority | PostgreSQL state 为 `pending/leased/retry_wait/completed/dead`；claim 使用 `FOR UPDATE SKIP LOCKED`、owner/generation/expiry CAS、bounded retry/backoff；Celery 仅是 wakeup |
| `tutor_queued_inputs` | conversation-scoped pending input authority | `pending/claimed/cancelled` closed lifecycle；pending position partial unique；最多 10 项由 conversation lock 保护；enqueue key、item version、claimed turn/revision/mode 与原始结构化 input metadata 可重放 |
| `tutor_capability_invocations`、`tutor_effects` | capability/effect receipt | 当前 revision、lease、Skill evidence 与 policy 必须同时通过；stale/interrupted effect 不调用 handler；effect 可保存 retry-root logical action key，committed 语义动作全局唯一复用 |
| `tutor_run_traces` | redacted diagnostic trace | trace 写入和导出都再次走 allowlist projection |
| `tutor_api_idempotency_records` | public Tutor / LearningTrack mutation replay | `(user_id, operation, idempotency_key)` 唯一；Tutor 输入与 `learning_track.*` mutation 都绑定 request hash 与安全 response JSON |

`POST /conversations/first-turn` 的 repository mutation 在一个 transaction 内创建 learner
conversation、fresh run、首条 learner message/input event 和 `input_received` process；任何
中间失败都会回滚，不留下空 conversation。普通 conversation-input 在 conversation lock
下仅在 idle 时创建 fresh run；active、pending request 或 paused 状态写入 `tutor_queued_inputs`。
partial unique index `uq_tutor_runs_interactive_foreground` 继续保证每 conversation 至多一个 active
interactive foreground run，`uq_tutor_queued_inputs_pending_position` 保证 pending FIFO position 不重复。

历史与内部 run 明确保持 `legacy_v1`；新 learner-visible fresh turn 显式写
`thread_turn_v2`。同一输入事务还会插入 dispatch job，并按 turn-created、message-added、
process-added 等 owning mutation 追加 conversation event；任何一步失败都会连同 message/run/job/event
整体回滚。v2 continuation intent 创建 typed request 并终结来源 run；response/receipt 解决 exact
request 后创建另一条 fresh run/job。旧 `/runs/{run_id}/inputs` 的 same-run revision/job rearm 仅属
legacy compatibility，不得被新 v2 mutation 调用。

Queue edit/delete/reorder/claim 与 `queue_paused/queue_pause_reason` 都在 conversation lock 下执行。
claim transaction 才创建 message/run/input/process/job，并把 item 写为 claimed；重复 drain 因 active run
或 item state CAS 返回 no-op。`logical_action_key` 由 user、conversation、stable retry root、effect type 与
payload hash 计算；同 run/effect 先走原 receipt replay，不同 retry turn 遇到 committed key 复用 commit ID，
遇到 proposed/ambiguous key fail closed。

conversation event payload 只保存 turn 或 item reference、control version、safe dispatch code 和
attempt，不复制 learner content、Tutor message、prompt、reasoning、trace、provider body 或 capability
args。snapshot 在 learner conversation 上持有 share lock，再读取 active turn、typed timeline 与
当前 sequence；历史 conversation 无 event backfill 时仍从 message/process 表投影，stream cursor
指向 sequence 0。dispatch job 最终 `dead` 时同事务终结 run、冻结 failed process、追加 safe error
item projection 与 `dispatch_dead` event。

终态约束：`tutor_runs.terminal_outcome` 与 `terminal_at` 必须同时为 `NULL` 或同时
存在。terminal transition、safe event、trace 与 curation outbox 由同一事务维护，
避免暴露半完成状态。provider 返回后的 lifecycle write 再次检查 cancellation/supersede；
stale run 只能收敛到安全 cancelled/superseded projection，不能写 Tutor message、title、
capability receipt 或 effect commit。
已经真实发生的 provider attempt 是独立执行/成本事实：run loop 在 provider 返回后、业务结果门禁前持久化其安全 receipt，因此 superseded/cancelled run 可以保留 usage，但仍不能获得 message、title、capability 或 effect 写权限。`input_tokens` 已包含缓存读取；`uncached_input_tokens = input_tokens - cached_input_tokens`，不得把 cached 再加回总输入。provider reported `total_tokens` 与 calculated `input_tokens + output_tokens` 分列保存；usage 缺失用 `usage_available=false` 与 `NULL` 表示，不能伪装成零。


## 2026-08-18：Codex plan-drafting 受控切换

`tutor_codex_runtime_health` 是无 learner ownership 的 shared infrastructure。server-side policy 只有在 feature enabled 且 latest heartbeat 对 exact allowlisted Runtime version、`deepseek-flash`、`aearn_deepseek`、`responses`、generation 和 freshness 全部通过时，才为全新 `plan_drafting` conversation 冻结 `codex_sidecar_v1`。既有 conversation 后续 fresh turn 与 Retry 继承原 Runtime；Queue item 只保存服务端冻结值，客户端字段不能影响。Harness/Codex worker 对同一 durable dispatch queue 按 `runtime_kind` 精确 claim，关闭 admission 不删除历史 binding/receipt，也不让 active run 跨 Runtime 续跑。

## 5. LearningTrack、计划路线、掌握度与教学 scope

### 2026-09-13：Frozen catalog scope

增量 fragment `220_plan_catalog_knowledge_scope.sql` 为 `tutor_track_plan_nodes`
增加可空 `catalog_knowledge_key`。INSERT guard 将非空映射与 immutable revision
`plan_json` 中的同节点映射/能力对照，并验证同语言、能力兼容的 published catalog；
旧 null 行与其 hash 不被回填改写。`tutor_plan_catalog_knowledge_key` 按
user/track/revision/node 精确解析，`tutor_artifact_catalog_knowledge_key` 经 Artifact
绑定的 TeachingSession frozen revision 解析。不存在或跨 scope 时 fail closed。
Artifact/Attempt owner guard 只用映射检查内容身份，根 `knowledge_key`、session/
assignment/version guard 和正式 Gate 的 progress owner 仍保持原路线节点身份。
修改映射必须发布新计划 revision；不得重标 published item、复用其他节点成绩或
改写旧 session/Attempt。仅内容映射并不构成学习完成、真实执行或独立内容覆盖证据。

LearningTrack 是新增的 track-scoped 教学权威状态，与旧 `learning_*` 表以及
user-level `tutor_plan_revisions` 明确隔离：

| 表 | 责任 | 关键不变量 |
| --- | --- | --- |
| `tutor_learning_tracks` | user + language + goal 的长期主线根 | `(id,user_id)` 复合 scope；`version` 用于 CAS；当前节点 FK 只能指向同 track progress |
| `tutor_track_plan_revisions` | predecessor-linked 完整计划版本 | predecessor 不得自指；canonical `plan_json` / SHA-256 不可普通 UPDATE/DELETE；状态 transition 与 activation timestamp 由 trigger 收口；每 track partial unique active revision，deferred constraint 保证 pointer/revision 一致 |
| `tutor_track_active_plans` | track 唯一 active pointer | revision、track、user 必须为同一复合作用域 |
| `tutor_track_plan_modules`、`tutor_track_plan_nodes` | revision 内不可变路线结构 | stable key/order 唯一；module/node 普通 UPDATE/DELETE 被 trigger 拒绝；prerequisite DAG 在应用 contract 验证 |
| `tutor_track_node_progress` | `(track_id,knowledge_key)` 长期进度 | stable key 跨 revision 保留；source revision 必须在同 track/user scope 内真实包含该 knowledge key；status 与 started/completed timestamps 双向一致 |
| `tutor_track_plan_migrations` | proposal/activation 影响与 CAS receipt | from/to revision 同 track/user；impact、expected version、idempotency/request hash 不可原地改写；lifecycle trigger 约束 proposed/confirmed/rejected/applied 与 timestamps |
| `tutor_mastery_evidence` | append-only trusted evidence | receipt 在 track + kind 内唯一；普通 UPDATE/DELETE 均被 trigger 拒绝；不能由模型正文直接生成 |
| `tutor_mastery_states` | projector 可重算的 bounded 状态 | 只引用同 progress/evidence scope；零 evidence 与 `last_evidence_id=NULL` 一致 |
| `tutor_conversation_learning_scopes` | conversation 的 general/planning/track binding | learning-track scope 必须引用同 user track；无 row 的旧 conversation 投影为 general |
| `tutor_run_learning_scopes` | fresh TurnRun 创建时的 immutable task/scope snapshot | run/user/conversation/track/progress 复合 FK；continuation 不得 UPDATE snapshot |
| `tutor_learning_plan_sessions`、`tutor_learning_plan_drafts` | planning lifecycle 与 immutable typed draft | session 保存 facts policy version；draft 保存生成时的 facts fingerprint/revision，确认时必须仍匹配 current projection |
| `tutor_planning_intake_facts` | append-only typed intake fact authority | field/value/revision/source evidence 都受 user/session/conversation/run/input 复合 scope；correction 追加 successor，current fact 是没有 `supersedes_fact_id` successor 的 confirmed leaf |
| `tutor_planning_question_events` | append-only stable question-state lineage | `question_key=field_key`；`previous_event_id` 每个 predecessor 最多一个 successor；current state 从 leaf 沿 predecessor 链解析，不能使用 `created_at` 或 UUID 猜测事务内顺序 |

PostgreSQL `now()` 在同一事务内稳定，因此同次 input 写入的 reopen、supersede 和
confirmed event 可以拥有相同 `created_at`。planning question current projection 必须先找
`previous_event_id` 没有 successor 的真实 leaf，再沿显式 lineage 回溯；
`uq_tutor_planning_question_events_previous` 阻止链分叉。`reasked_blocked` 是审计事件，
读取对外 question state 时跳过该节点并继续使用其 predecessor 状态。

计划激活先锁 track 并校验 `expected_track_version`、direct predecessor 与 migration
状态，再切换 revision/pointer。相同 `knowledge_key` 的 progress/mastery 保留；新 key
依据其 prerequisite 的已完成状态初始化为 available 或 locked。移出 active plan 的旧
progress/evidence 不在 activation 时删除，roadmap/progress 汇总只读取 active revision
节点。

`MasteryProjector` 只消费 persisted trusted evidence summary，按 independence 权重产生
`confidence`、`mastery_level`、strength/weakness 与 projector version。它不依赖 provider，
同一有序 evidence 集可确定性重算。

本地 data summary/export 包含 LearningTrack、revision、node/progress 与 bounded mastery
state，但不导出 raw `plan_json` 或 evidence body/hash。confirmed reset/delete 先将该
用户仍 active 的 interactive runs 安全 terminalize，再在 transaction-local purge capability
下按 run/conversation scope -> mastery -> progress/migration -> node/module -> active pointer ->
child-first revision -> track 的外键顺序清理，并删除该用户 API idempotency；cutover
inventory 将任一新 track/scope/evidence 行视为 target contamination，绝不在切换中删除。

## 6. Skills、capability、effects 与执行器

- Skills 以 Git-owned catalog 的 exact `id@semantic-version` 选择，永久保存
  evidence hash。别名、范围、`current` 与未知 Skill 不能成为 durable proof。
- capability/effect descriptor 只允许声明字段；模型正文不能成为 URL、文件路径、
  shell/SQL、用户 ID、镜像、命令或数据库 target。
- `tutor_execution_intents`、`tutor_execution_jobs`、
  `tutor_execution_attempts`、`tutor_executor_health` 是 explicit-only
  container executor 的 durable queue/health 事实。API、普通 worker 和
  Desktop 不导入 runtime client，也没有 host subprocess fallback。
- Proactive origin 永远不允许 `runner.execute` 或 learner-code execution。

## 7. Proactive scheduler 与 curation 队列

| 表 | 责任 | 默认/安全边界 |
| --- | --- | --- |
| `tutor_proactive_preferences` | 每用户 `enabled` 与 `hard_paused` | 默认 `enabled=true`、`hard_paused=false`；bootstrap 将旧的未暂停 disabled preference 恢复为 enabled |
| `tutor_proactive_signals` | safe signal、source hash、dedupe/disposition | interactive terminal metadata 仅含 run ID/outcome/time hash；不保存 message/prompt/code/trace/provider diagnostic |
| `tutor_proactive_candidates` | durable candidate、lease、retry、no-action | `(user_id, dedupe_key, dedupe_bucket_at)` 唯一；verified gate/pause/budget/cooldown/concurrency/circuit 必须通过 |
| `tutor_scheduler_audit` | scheduler decision evidence | 仅保存安全 code/details，支持审计不泄露内容 |
| `tutor_memory_curation_outbox`、`tutor_curation_proposals` | redacted compaction/proposal envelope | 非 raw provider payload store |
| `tutor_curation_jobs` | curation lease/retry lifecycle | 默认 budget/output tokens 为 0，inferred memory 默认关闭 |
| `tutor_curation_projection_receipts` | 正常 policy/service validation 后的 projection 结果 | 只能记录 committed/no-action/stale/failed 的安全事实 |

生产 `scan_due_signals` 的 `user_id=None` 语义是全局队列扫描。repository 支持
显式 user scope 仅供 fixture/maintenance isolation；它不能改变正常 worker 的
全局行为。

## 8. Learner-state projections

| 表 | 当前业务事实 | 不变量 |
| --- | --- | --- |
| `tutor_plan_revisions` | 不可变 plan revision | revision 含 evidence、diff 与 predecessor；不会写旧 `learning_plans` |
| `tutor_active_plans` | 唯一可变 active pointer | 只能指向当前用户 revision |
| `tutor_plan_revision_actions` | append-only activation/rollback action | 用户 rollback 只可回到直接 predecessor |
| `tutor_memory_preferences` | inferred-memory setting/version | setting version 使 stale queued work 失效 |
| `tutor_memory_entries` | objective fact 或 inference | correction 追加 replacement；delete 是受控 state transition |
| `tutor_context_summaries` | safe compacted context projection | v2 绑定 conversation、schema/policy、结构化 JSON、coverage、source hash 与 prior lineage；UPDATE 被 append-only trigger 拒绝，legacy 短摘要可保留但不进入 v2 loader |
| `tutor_activity_records` | append-only learner-safe activity | 可从 effect/run 追溯，但不含 internal payload |
| `tutor_inbox_items` | 一条 activity 对应的可读/dismiss 投影 | `unread/read/dismissed` 生命周期与时间戳约束 |

### 8.1 长对话结构化摘要

`tutor_memory_curation_outbox.projection_kind` 区分旧的 `memory_or_summary` 与
`context_summary`。v2 outbox 必须同时具备 exact schema/policy version、连续退休消息
ID/hash、conversation coverage cursor、source hash，以及成对的 prior summary
identity/hash；相同语义 evidence 在 high-water 与 terminal lifecycle 之间共用一个
curation idempotency key。`tutor_curation_jobs.projection_kind` 必须与 outbox 一致。

`tutor_context_summaries` 的 v2 row 通过 composite FK 证明 user/run/conversation、
outbox、covered message 与 prior summary 均在同一 scope。结构化列必须整组存在，
`source_hash`/`prior_summary_hash` 为 SHA-256，并使用
`(user_id, conversation_id, covered_through_created_at DESC,
covered_through_message_id DESC)` 检索最新 coverage。summary 内容不可原地 UPDATE；
纠正通过追加新 row。用户级 reset/delete 可按既有依赖顺序物理删除 summary
projection，但不能因此删除或改写 `tutor_messages`。公开 export 默认不暴露内部
`summary_json`。

## 9. 公开投影与删除规则

- repository 是唯一可将表行转成 API/SSE payload 的层；SQL/JSONB 不得被 route
  直接串行化为用户输出。
- `tutor_messages` 的 raw learner content 不复制到 event、trace、outbox、
  inbox、activity、capability/effect/provider-attempt receipt 或 idempotency response。
- 所有 user-scoped query/mutation 都显式带 user ID；复合外键、unique constraint、
  lease generation、CAS 和 `FOR UPDATE SKIP LOCKED` 防止跨用户和重复 worker 写入。
- 删除本地用户是显式 confirmed 用户数据操作。cutover 不是“reset”捷径，且
  pre-cutover target state 不能用普通 reset 清空。

## 10. 历史表与当前读取规则

旧表仍可能包含 `learning_plans`、`plan_modules`、`knowledge_points`、
`exercises`、`attempts`、`review_states`、`review_logs`、`notes`、
`onboarding_*`、`learning_messages` 和 `review_messages`。在当前代码中：

- 它们不构成 `/api/tutor` 的输入、上下文、effect 或 UI state。
- `harness_cutovers` 只能把它们作为 server-side inventory/delete target，
  并在成功后验证同一 scope 已清空。
- 历史概念如 Attempt、FSRS、hidden tests 与 source attribution 不会被 Tutor
  API 重建、展示或静默写入；历史归档不会被当作 current runtime source。

## 11. Schema 验证

执行顺序必须串行，避免共享 PostgreSQL bootstrap fixture 并发导致 deadlock 或
`tuple concurrently updated`：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/database/test_db_bootstrap.py tests/learning/test_learning_track_repository.py tests/integration/test_harness_cutover.py
uv --directory .\aearn\services\api run python -m pytest tests/tutor/test_tutor_run_repository.py tests/tutor/test_tutor_proactive_default_delivery.py
```

完整命令、结果和 residual risk 以
[Release Readiness Ledger](../qa/tutor-harness-release-readiness.md) 为准。

## 2026-08-10：计划制定持久化

`tutor_learning_plan_sessions` 是 user/conversation-scoped planning root，同一用户最多一条 `collecting | draft_ready` session；它保存 current draft pointer、确认 track、版本、facts policy version 与 allowlisted safe error，不保存 raw prompt/history/provider body/reasoning。`tutor_learning_plan_drafts` 保存确认所需的 profile、canonical plan、registry-owned source summary、content hash、source run/revision，以及生成时的 facts fingerprint/revision；草案 append-only，`(session_id,draft_version)` 与 `(source_run_id,source_input_revision)` 唯一。current pointer 使用 deferrable composite FK 保证 draft 属于同一 user/session。

`tutor_planning_intake_facts` 与 `tutor_planning_question_events` additive 地补足 draft 前的
规划 authority。事实 correction 和 question transition 都追加 row，不原地改写；复合 FK
把 source message/run/input revision 锁定到同一 user/session/conversation。local export 仅
输出 normalized value、lineage/source identity 与安全状态，显式省略 value/event hash 和
gate reason；reset/delete 按 question leaf-to-root、fact high-revision-to-low-revision、draft、
session 的顺序清理。cutover target inventory 已将四张 planning 表全部视为 target state。

## 2026-08-11：LessonDocument authority

`tutor_lesson_documents` 保存共享 immutable standard document 与 user/track-scoped
personalized document。standard 行没有 user/track owner；personalized 行必须引用匹配语言和 `knowledge_key` 的 standard document、active plan revision、profile hash 和可选 predecessor。canonical blocks、coverage、Gate slot 和引用集合进入 content hash。

`tutor_lesson_source_snapshots` 在发布事务中复制 registry/version/URL/section、grounding chunk ID、raw document hash、chunk hash、抓取/冻结时间和 bounded excerpt；它不对可替换的 `grounding_chunks` 建立删除阻塞 FK。`tutor_lesson_block_citations` 和 `tutor_lesson_gate_slots` 冻结 block-to-source 与公开 Gate contract。

`tutor_lesson_assignments` 保证每个 `track_id + knowledge_key` 最多一个 active assignment。开始后 `started_at`、document identity 与 activation lineage 不可改写；更新先创建 direct proposed successor。`tutor_lesson_authoring_runs` 保存 pending/claimed/running/terminal、lease、expected versions、source set、safe failure 和结果 identity；`tutor_lesson_authoring_attempt_receipts` 只保存 append-only provider/model/protocol/outcome/usage/hash metadata。

local export 包含 personalized blocks、assignment 与 citation metadata，但省略 evidence excerpt 全文、prompt/body/reasoning 和内部 quality details。reset/delete 在 transaction-local purge capability 下 child-to-root 删除 user-owned Lesson rows；共享 standard documents 与其 source snapshots 保留。cutover target inventory 只统计 personalized document、assignment 和 authoring run，不把共享 standard 内容归给某个用户。

### 2026-09-08：Lesson attempt 安全诊断

`tutor_lesson_authoring_attempt_receipts.diagnostic_json` 为 `jsonb NOT NULL DEFAULT '{}'`，数据库 CHECK 要求 object。fresh create 和 additive `ADD COLUMN IF NOT EXISTS` 同时维护；历史行保持空对象兼容，无新增 user-owned 表或删除顺序变更。

2026-09-08：应用侧私有诊断继续读取空对象和 `lesson_author_attempt_diagnostic_v1`；新响应元数据使用 `lesson_author_attempt_diagnostic_v2`，增加封闭的 `provider_response`（状态、截断原因枚举、请求输出额度/思考强度、可见输出字符数）与可空的 `reasoning_tokens`。未知用量保留 NULL；reasoning 是 output 的子集，不再次累加总用量。不得存入原始响应、思考正文或任意 provider 错误文本；公共 API/SSE/用户导出不投影这些诊断。复用现有 JSONB 列，不需要新增数据库迁移或回填历史记录。

新诊断只允许版本、standard/personalized document kind、文档内 attempt index、失败阶段、稳定 issue codes/locations 和 feedback hash。constraint 文本、prompt、provider body、reasoning、raw candidate、credential 不持久化。receipt 的 success 只在 parse/identity/quality 全部通过后记录；每次失败仍单独记录，`(run_id, attempt_index)` identity、append-only trigger 和 usage 缺失时 NULL 语义保留。

## 2026-08-11：练习 Gate、Attempt 与模块诊断 authority

新练习 authority 由十二张 additive 表组成：`tutor_exercise_versions`、`tutor_exercise_private_rubrics`、`tutor_lesson_gate_bindings`、`tutor_lesson_gate_states`、`tutor_module_diagnostic_versions`、`tutor_module_diagnostic_sessions`、`tutor_module_diagnostic_items`、`tutor_exercise_attempts`、`tutor_exercise_attempt_submissions`、`tutor_exercise_attempt_results`、`tutor_exercise_hint_receipts` 和 `tutor_exercise_execution_links`。共享 exercise/diagnostic version 与 private rubric 不属于单个用户；binding/state、Attempt、submission/result/hint、diagnostic session/item 和 execution link 通过复合 FK 固定 exact user/track/plan/Lesson/diagnostic scope。

`gate_kind=knowledge_check | guided_practice | independent_practice` 继续描述 Lesson 教学形态；`requirement_kind=required | recommended | diagnostic` 单独控制路线阻塞。binding 和 exercise/rubric 由 canonical hash/version 冻结。Gate state 只允许 `available | in_progress | passed | remediation_required` 的受控生命周期；Attempt、submission、result、hint 与 execution link 为 append-only/immutable，普通 UPDATE/DELETE 被 trigger 拒绝。

`tutor_exercise_attempts` 使用 owner shape CHECK 分离 Lesson `run | submit` 与模块 `diagnostic_submit`。完整提交只保存在 `tutor_exercise_attempt_submissions.content_text`，公共读取和 export 只投影 hash/摘要。terminal `tutor_exercise_attempt_results` 每个 Attempt 最多一条；required submit 的 result、mastery evidence、Gate CAS、progress completion 和 unlock 在同一数据库事务内 exactly-once 投影。`run` 结果不进入 Gate/mastery/progress。

现有 `tutor_execution_intents` 通过 `source_kind=tutor_message | exercise_submission` 扩展，`tutor_execution_jobs` 通过 `owner_kind=tutor_effect | exercise_attempt` 扩展；两者使用 exact one-of CHECK 和复合 FK 保留旧 Tutor scope，同时允许 Gate 复用同一 claim/lease/launch-token/terminal 队列。Gate 路径不创建 Tutor conversation/message/effect。`tutor_exercise_execution_links` 固定 Attempt 到 existing intent/job 的一对一关系。

`tutor_mastery_evidence.evidence_effect` 区分 `reinforcing` 与 `observational_non_degrading`。失败或部分通过的模块诊断只追加 observation/weakness，不降低既有 confidence；全部核心能力独立达到版本化阈值后，session 才可引用 predecessor-linked proposed plan revision。只有 confirm transaction 可把 session 置为 `confirmed`、激活 successor、写 `diagnostic_skipped` 并重算下游 availability。

local export 省略完整 submission、hidden/private rubric/reference answer 和内部 execution 信息；reset/delete/cutover 在 transaction-local purge capability 下按 execution link/result/hint/submission/Attempt/Gate/diagnostic child-to-root 清理 user-owned rows。共享 curated exercise/diagnostic versions 与 private rubric 保留。Bootstrap twice 必须重复成功，并断言 owner/source one-of、scope FK、唯一性、immutability/lifecycle trigger 和索引存在。


## 2026-08-12：受控 Action Runtime 持久化

`tutor_action_invocations` 保存统一 action orchestration identity、exact descriptor/adapter、
run/input revision、lease owner/generation、action generation、idempotency/stable key、catalog/policy
证据与 resource fingerprint；不保存 raw arguments。其生命周期由数据库 trigger 与应用同一
迁移表约束，终态不可更新或普通删除。`tutor_action_attempts`、
`tutor_action_verifications`、`tutor_action_receipts` 都是 append-only evidence；只保存安全状态、
authority reference/hash、结果/验证 hash、稳定 diagnostic/recovery code 与有界 safe JSON。

Action 表不复制领域事实：`capability_invocation` 指向现有 capability receipt，`plan_draft`
指向 immutable plan draft，`execution_job` 指向现有 execution job/result，未来 effect 仍指向
原 effect receipt。`(run_id,idempotency_key)` 防止同 key 重复执行；current verified partial
unique index `(run_id,input_revision,stable_action_key)` 防止同 revision 的语义重复 action。
复合外键固定 invocation/receipt 的 run、user、conversation scope，parent/retry lineage 只能
留在同一 run。

Action reserve 必须匹配当前 `tutor_runs` 的 input revision、exact active lease owner/generation、
未过期 lease、catalog digest、policy fingerprint 与非 terminal/cancelled/superseded 状态。
本地 export 只返回 bounded action summary，不返回 raw result/hash；confirmed reset 使用既有
transaction-local purge capability 按 receipt -> verification -> attempt -> invocation 顺序删除。
cutover inventory 将四张 action 表视为 target state，不会在切换中静默清除。


## 2026-08-12：模型代码审核 authoring 与发布 authority

`tutor_model_review_authoring_runs`、`tutor_model_review_authoring_attempt_receipts`、
`tutor_model_review_candidates`、`tutor_model_review_validation_runs`、
`tutor_model_review_validation_checks`、`tutor_model_review_publications` 与
`tutor_model_review_evidence_receipts` 保存 user/track/Gate scoped 的生成、受控验证、发布和
learner assistance 事实。candidate 公共题面与 private rubric/test payload 分列并各自 hash；
provider candidate 只保存教学标题、学习者说明和候选代码，server-owned private payload 保存
受控 test DSL、expected outcome、finding/rubric/proof、score policy 以及完整
`template_id + template_version + template_contract_hash`。只有
`model-code-review.validate@1.0.0` 的 verified authority 才能原子发布
`tutor_exercise_versions` / `tutor_exercise_private_rubrics` 与 exact Gate binding。

共享执行队列新增 `source_kind=model_review_candidate` 与
`owner_kind=model_review_validation`，仍复用既有 intent/job/attempt、reviewed runtime lock、
lease、retry、cancel 与 terminal contract。trusted-input resolver 只在 exact claimed scope 读取
private DSL，并在 sandbox wire payload 中剥离 template test id、`candidate_expected_pass` 和
`proof_ids`；这些 metadata 只用于 API 侧验证结果与服务端模板预期是否一致。学习者 submit 为
`structured_answer`，完整 JSON 只
保存在 private submission 表；export 只投影 verdict 与用户 finding 的 id/kind/line/category/
severity 摘要。private candidate、rubric、test、matcher、proof 与 submission 自由文本均省略。

Authoring 对 candidate/validation/publication 的环形引用使用 `ON DELETE NO ACTION
DEFERRABLE INITIALLY IMMEDIATE`。`RESTRICT` 即使标记 `DEFERRABLE` 仍会立即检查，不能用于
transaction-local child-to-root purge。confirmed reset 先 terminalize 内部 proactive run，
删除 evidence/action/execution/check/publication/validation/candidate/author receipt/authoring，
再删除该 authoring 独占的 internal run/conversation；去个性化的 immutable published
exercise/rubric 保留。cutover inventory 将上述七张 user-owned 表显式计为 target state。

## 2026-08-12：Track-scoped ReviewSession 与调度 authority

正式复习由七张 additive user-owned 表组成：`tutor_review_schedule_states`、
`tutor_review_schedule_events`、`tutor_review_sessions`、
`tutor_review_warmup_receipts`、`tutor_review_items`、
`tutor_review_hint_receipts` 和 `tutor_review_finalizations`。schedule state 对
`track_id + knowledge_key` 唯一，并用复合 FK 固定 user/track/plan revision；event、warmup、
hint 和 finalization 是 append-only receipt。session 生命周期为
`blocked | active | ready_to_finalize | finalized | cancelled`，blocked 保持可恢复且不会占用
第二个 active session identity。

`tutor_exercise_attempts` 的 owner shape 增加 `review_submit`：必须同时绑定 exact
`review_session_id + review_item_id + track_id + plan_revision_id + knowledge_key`，并保存 expected
review session/item version。每个 review item 最多一个 Attempt；submission/result 继续使用既有
private artifact 和 immutable terminal result。执行依赖题复用 `tutor_execution_intents`、
`tutor_execution_jobs` 与 `tutor_exercise_execution_links`，不新增 queue 或 Tutor conversation。

warmup/hint/中间 Attempt 不更新长期 mastery/schedule。唯一 finalization 在一个事务中锁定
session、track、schedule 和 terminal Attempts，写一条 `tutor_review_finalizations`、一条
`tutor_review_schedule_events`、一条 `tutor_mastery_evidence(evidence_kind='review')` 并 CAS 更新
`tutor_review_schedule_states`。计划 revision 激活按稳定 `knowledge_key` 写 retained/suspended
migration event；确认的模块诊断 skip 建立低频 schedule。actionable due count 查询包括普通
`due_at <= now()` 和 `risk_level='critical'`，后者仅在其为当前节点前置知识时投影短 Gate。

local export 只包含 schedule/session/finalization 的有界摘要和 Attempt owner ID，不导出
context snapshot/hash、selection reason、完整 submission、private rubric/test 或 event state JSON。
reset/delete 使用既有 transaction-local purge capability，按 finalization/event/hint/result/
submission/Attempt/item/warmup/session/schedule 的 FK 逆序清理。cutover inventory 显式统计七张
review 表；bootstrap twice 必须断言 owner CHECK、复合 FK、唯一索引、lifecycle/immutable trigger
和 repeatable additive migration。


## 2026-08-12：Tutor message context reference authority

`tutor_message_context_references` 是 user-owned append-only 表。每行保存 exact
`user_id + conversation_id + run_id + message_id + input_revision + reference_index`，并用复合 FK 确保 learner
message、run 和 input event 属于同一作用域。`(run_id,input_revision,reference_index)` 与
`(message_id,reference_index)` 唯一；`reference_kind` 只允许 `lesson_selection | exercise_feedback |
execution_result | review_feedback`。普通 UPDATE/DELETE 由 immutable trigger 拒绝，用户级 confirmed purge 才能按
child-to-root 路径删除。

表中的 `safe_payload_json` 必须符合 `tutor_context_reference_v1`，`safe_payload_hash` 是 canonical JSON SHA-256。
artifact identity 列只保存必要的 track/knowledge/document/attempt/review session/exercise version/source version/hash；
公开读取会重新校验 safe payload hash。Lesson safe snapshot 保存服务端重建的 bounded excerpt；Attempt/Review snapshot
只保存 terminal outcome、score、assistance、safe feedback、capability scores 和公开时间；execution snapshot 只增加安全
job identity/state。不得存 learner message 的副本、完整 submission、private rubric/test/reference answer、raw stdout/stderr、
command/path/container、provider body、reasoning、credential 或 secret。

Tutor input 在外层事务中先创建/锁定 message、run input event 与 immutable run scope，再验证 source artifact 并插入全部
reference rows；任何 source/scope/version/hash/terminal 校验失败都回滚整条 input。History 按 message + reference index
重放，context loader 按 run + input revision 读取，因此后续 Lesson migration、Review schedule 更新或 artifact pointer 变化
不会改写既有快照语义。

local export 仅输出 safe reference projection 与 hash；reset/delete 在删除 Tutor message/run 前先删除引用。cutover target
inventory 把该表视为 pre-verification target state。bootstrap twice 必须断言复合 FK、唯一索引、kind CHECK、immutable trigger
和 repeatable additive schema 均存在。

## 2026-08-12：最终 schema 与迁移清单审计

`HarnessCutoverService` 的 target inventory 现在逐表列出每个 user-owned `tutor_*` 表，包括 run/message/run-event/conversation-event/interactive-dispatch job/trace/checkpoint、Action、execution attempt、Lesson source/citation/Gate slot/authoring receipt、Review 与 context reference descendants。只有无 learner ownership 的 `tutor_catalog_snapshots`、`tutor_executor_health`、去个性化 `tutor_exercise_versions` / `tutor_exercise_private_rubrics` 与 `tutor_module_diagnostic_versions` 被显式归类为 shared。

`test_cutover_inventory_explicitly_classifies_every_tutor_table` 读取真实 PostgreSQL `information_schema.tables`，要求 schema 中所有 `tutor_*` 表恰好等于 target inventory 与 shared allowlist 的并集；新增表若未分类会直接失败。target 任一行存在都会阻断 clean-slate cutover，防止把当前 Tutor/LearningTrack 状态与旧数据混合删除。

迁移策略保持非转换：旧 `learning_*`、user-level Tutor plan、旧 review/notes、旧 checkpoint 只参与 exact inventory/deletion，不会生成 LearningTrack、Lesson、Attempt、mastery 或 ReviewSession。普通 reset/delete 清理当前用户拥有的学习状态和私有提交，但保留共享 immutable exercise/catalog；feature rollback 不执行数据删除，也不把 verified receipt 回退为旧 runtime 入口。


## 2026-08-14：类型化请求与权威续轮

`tutor_interaction_requests` 使用 `(id,user_id,conversation_id)` 与 `(item_id,user_id,conversation_id)`
复合 identity，`source_turn_id`、`answer_turn_id`、`answer_message_id` 和
`tutor_runs.response_to_request_id` 不能跨 user/conversation。`state=pending` 时 response/receipt hash、
answer lineage 与 `resolved_at` 必须为空；resolved state 必须有 `resolved_at`。partial unique index
`uq_tutor_interaction_requests_pending_conversation` 保证同一 conversation 最多一个 blocking request。

`planning_input` 只能保存七个 allowlisted key 与 `tutor_planning_questions_v1`；approval 必须保存
server-owned proposal identity/authority key/risk；authority request 必须保存 exact request hash，receipt
则绑定 issuer/subject/scope/request/result hash 与 verification result。公开 projection 从 typed columns 和
allowlisted JSON serializer 构造，不直接回放 provider JSON。cutover target inventory 已显式包含该表。


## 2026-08-14：thread/turn v2 全局 cutover authority

`tutor_thread_turn_cutovers` 保存单例 state/generation/summary hash/safe counts/block code/operator idempotency/timestamps；`tutor_thread_turn_cutover_events` 是 append-only 安全审计。两表是 shared infrastructure。preparing 下 legacy waiting run 失败并要求 fresh v2 turn，其他可取消 active run 立即 cancelled/清 lease；ambiguous effect/action receipt 保持原状并使 singleton blocked。enable 只允许 ready 的 exact generation+summary，rollback 只回到 ready/read-only，不恢复 legacy mutation 或数据。

## 2026-08-15：Tutor 公开思考文本流 authority

`tutor_messages` additive 新增 `public_thinking_text text NOT NULL DEFAULT ''` 与
`char_length <= 1280` CHECK；`chk_tutor_messages_public_thinking_single_representation` 要求
新文本非空时 `public_thinking_steps_json` 必为空。旧 steps 不回填、不改写，读取层以
`"\n\n"` 连接为统一纯文本；新消息只写文本列。

`tutor_turn_public_thinking_streams` 以 `run_id` 为主键，并通过
`(run_id,user_id,conversation_id)` 复合 FK 固定作用域。`input_revision`、
`decision_iteration`、`generation`、`provider_attempt` 建立 stale fence；state 仅为
`active | complete | discarded | accepted`，时间戳 CHECK 保证状态与
`completed_at/discarded_at/accepted_at` 一致。`thinking_text` 最多 1280 字符，
`next_chunk_sequence >= 1`，可选 `last_public_event_sequence` 复合 FK 指向同 conversation event。

begin/append/reset/complete/discard 每次都锁定当前 run/stream，验证 foreground、lease、revision、
generation 后，在同一短事务更新文本并追加 `turn_output`。`append` 只写累计安全的 provisional
前缀；provider transport EOF 只结束 projector 解析，不得把 stream 置为 `complete`。只有完整 decision
通过 schema/domain/安全校验并与 streamed text exact match 后，gateway 才调用 complete。成功终态消息
或 typed request 必须在同一事务比较最终 decision 文本、写 canonical public item、把 stream 置为
`accepted` 并追加 owning conversation events；任一步失败全部回滚。repair、context rebuild、Interrupt、
supersede、stale revision、lease loss 或失败路径只能 reset/discard，不得接受旧 generation。

该表纳入 cutover target inventory、local export/reset/delete child-first 清单与 bootstrap-twice
验证。公共表只保存 learner-safe 文本；raw JSON、provider reasoning/body/event、prompt、trace、
diagnostic、credential 和 secret 禁止落入该表、message 列或 conversation event。

## 2026-08-20：Conversation Runtime thread 与 raw text projection

| 表 | 责任 | 关键不变量 |
| --- | --- | --- |
| `tutor_conversation_runtime_threads` | 一个 learner conversation 对应的持久 Codex App Server thread | owner/conversation scoped FK；每 conversation/runtime 最多一个 active row；固定 `deepseek-flash` + `aearn_deepseek`；external identity immutable/private；记录 native/adopted legacy/reseed lineage 与 resume/compaction 时间 |
| `tutor_run_runtime_bindings` | fresh TutorRun 到同 conversation thread 内一个新 Codex turn 的绑定 | 增加 conversation thread FK；run 仍唯一，external turn 唯一；不再要求 external thread 在 run binding 中唯一；input/lease/connection generation fence 仍控制投影 |
| `tutor_runtime_text_items` | owner-scoped raw reasoning 与 final-answer current/history projection | `(binding, external item hash, channel)` 唯一；channel/state/sequence/hash/connection generation 闭合；streaming 可追加，completed/discarded/blocked terminal immutable；completed item 仅允许一次关联同 conversation 正式 message |

`reasoning` 和 `final_answer` raw text 只存在 `tutor_runtime_text_items`，不得复制进 runtime receipt。phase 校正为 commentary 或任意 turn terminal 遇到未完成 item 时，必须把 row 转为 `discarded`，同时将 `text=''`、`content_hash=NULL` 并写入 terminal 时间，禁止留下可恢复的 commentary 或永久 `streaming` row。`tutor_runtime_item_receipts` 仍只保存 event/item kind、sequence、hash、safe code、projection status 和 Aearn public reference；commentary/summary 只能形成 nonpublic receipt。新表纳入 bootstrap twice、cutover inventory、owner-scope FK 和 transaction-local purge guard。删除顺序必须先 text item/receipt/error，再 run binding，再 conversation thread，最后才允许删除 owning run/conversation。

## 2026-08-21: Course intent taxonomy

| Table | Purpose | Boundary |
| --- | --- | --- |
| `tutor_learning_intents` | Shared closed planning-direction taxonomy | `intent_key`, state, display name, and policy version; classified as shared Tutor metadata |
| `language_course_intent_tags` | Course UUID to intent-key relation | composite primary key, rank `0..100`, primary marker, policy version, and restrictive foreign keys |

`assert_language_course_intent_coverage()` requires every active course to have an active tag and every active intent to have an active course. Deferred constraint triggers check the final transaction state for course publication, intent activation, and tag mutation. Bootstrap performs the only slug-based backfill, validates coverage, and is repeatable. Runtime shortlist queries join active course UUIDs and active tags and never inspect course slug, title, or description.

## 2026-08-21：Runtime source/projection sequence 与合并审计

`tutor_runtime_item_receipts.event_sequence` 保留为兼容列并与新增 `projection_sequence` 严格相等；所有 PostgreSQL reducer、`tutor_runtime_text_items.last_event_sequence`、conversation `turn_output.chunk_sequence` 与 Desktop reducer 都以 projection sequence 为顺序 authority。provider-normalized source sequence 不进入公共 DTO。

每个有 source evidence 的 receipt 必须同时保存 `source_sequence_start`、`source_sequence_end`、`source_delta_count` 与 `source_content_hash`。四者要么全部为空（仅允许本地 synthetic control/recovery event），要么形成闭合连续范围且 count 精确等于范围长度。字段只保存数字与 SHA-256；raw delta、reasoning/final text、provider body、external identity 和工具参数仍禁止进入 receipt。`tutor_runtime_text_items` 是 owner-scoped text authority，completed item 继续校准全文。

## 2026-08-23：TeachingSession durable authority 与 action receipt

一条 LearningTrack 继续只绑定一条长期 learner-visible Tutor conversation；知识点教学分段由 `tutor_teaching_sessions` 持久化，不创建并行聊天根。session 冻结 exact `user_id + track_id + conversation_id + knowledge_key`，以及 track version、active plan revision、progress version、active Lesson assignment/version、LessonDocument/content hash。partial unique 只约束 `active | paused` current session；authority 变化时旧 session 追加 `authority_pause` checkpoint 并置为 `blocked`，新 session 通过 `predecessor_session_id` 形成 immutable successor lineage。旧 conversation/history 不从聊天正文猜测或回填 session。

`tutor_teaching_session_checkpoints` 是 predecessor-linked append-only CAS 链。`session_version=1` 必须没有 predecessor，后继版本必须引用唯一 predecessor；session 的 `current_checkpoint_id` 与 `version` 一起推进。checkpoint 的 bounded typed state 只包含 objective、active/suspended focus、unresolved-question 摘要、covered concept、evidence cursor、pause reason 与 recommended action；raw prompt、provider reasoning/body、完整题目/提交、private test/rubric、command/path/secret 不进入公共投影或 export。

`tutor_run_stimulus_events` 对每个 teaching-scoped fresh run 保存且只保存一个 exact stimulus：`learner_message | teaching_control | domain_event`。learner stimulus 必须复合引用 exact `tutor_run_input_events(run_id,message_id,input_revision)`；control/domain stimulus 不创建伪 learner message，run origin 仍为 `interactive`，不能滥用 proactive。`tutor_run_teaching_scopes` immutable 冻结 session/checkpoint/stimulus 与 track/plan/progress/assignment/document fence。effect commit、waiting-result 和 terminal-result 持久化前重新读取 current authority；任一 scope/version/pointer 已变化都 fail closed，不能写 effect 或 learner-visible terminal output。

`tutor_teaching_action_receipts` 每个 run 最多一条，复合引用 exact run/session/new checkpoint/stimulus。v2 row 在既有 closed action、objective/focus identity、focus resolution、pause kind、bounded source handles、public-message SHA-256 与 selected context IDs/hashes 上，新增 `teaching_moves_json`、`learner_response_mode`、`schema_version=teaching_action_receipt_v2` 与 `policy_version=lesson_teaching_policy_v2`；不保存 public message 正文、provider body、prompt 或 reasoning。DB CHECK 要求 v2 有 2--4 个 closed、互不重复的 moves，并约束 composer/action 兼容；v1 默认空 moves/none 以兼容历史行。receipt 与 message/checkpoint/session/run terminal 在同一事务提交，普通 UPDATE/DELETE 由 append-only trigger 拒绝。

五张 user-owned 表全部属于 cutover exhaustive target inventory，并进入 local summary/export/reset/delete。删除在 transaction-local purge capability 下按 `action receipt -> run teaching scope -> stimulus -> checkpoint -> session` 执行，再清 Lesson/track root；session current-checkpoint、checkpoint predecessor/source-stimulus 与 receipt lineage 使用 deferred `NO ACTION`，使同一事务 child-to-root 清理可验证且 bootstrap twice 幂等。早期本地 `RESTRICT` source-stimulus FK 必须在 bootstrap 时 drop/recreate 为 deferred `NO ACTION`，否则已有 action checkpoint 的 reset 会在中途失败。

## 2026-08-23：Domain event admission 与 checkpoint-backed teaching summary

Gate/Attempt terminal、Review finalization、progress completion 与 Lesson assignment migration 不新增第二套业务事实表。各 owner 先提交既有 result/evidence/schedule/progress/assignment authority，`TeachingDomainEventAdapter` 再以 durable source ID/version 生成 `domain_event` stimulus。`uq_tutor_run_stimuli_domain(teaching_session_id,domain_event_kind,source_id,source_version)` 与 admission 前 exact receipt lookup 共同保证重复事件返回同一 run，而不是依赖 unique violation 创建孤儿 run。

长期 teaching summary 复用 `tutor_teaching_session_checkpoints` 的 append-only predecessor chain，不新增 mutable summary table。`teaching_session_summary_v1` 是受控投影：objective、active/suspended focus、unresolved questions、covered concepts、evidence cursors、pause/completion 与 source checkpoint/authority hashes。loader 每次重新验证 current checkpoint/session version、authority snapshot 与 canonical source hash；任一失配都不进入 provider context。current summary 进入 optional working-summary section，required teaching context 使用 compact authority projection；最多选择一个 exact predecessor summary，默认不全量重放长期 conversation。

## 2026-08-27：Teaching action receipt v2

`080_lesson_teaching_practice.sql` 对既有 `tutor_teaching_action_receipts` 做 additive bootstrap：`teaching_moves_json JSONB NOT NULL DEFAULT '[]'::jsonb`、`learner_response_mode TEXT NOT NULL DEFAULT 'none'`、`schema_version TEXT NOT NULL DEFAULT 'teaching_action_receipt_v1'` 与 `policy_version TEXT NOT NULL DEFAULT 'lesson_teaching_policy_v1'`。历史 v1 row 因默认值继续可读；新提交只能写 v2 schema/policy。

repeatable bootstrap 先删除旧同名自动 CHECK，再建立稳定命名的 moves、response-mode 与 version-shape constraints。v2 moves 必须是长度 2--4 的 JSON string array，值属于 closed enum且位置不重复；composer 只与 `check_understanding | wait_for_input` 共存，none 禁止这两个 action。receipt 仍 append-only，local export 只增加 safe moves/mode，不增加 public message、prompt、provider body 或 reasoning。

## 2026-09-01：Teaching Artifact commit、branch lineage 与 continuation intent

`tutor_teaching_action_receipts` additive 支持 `teaching_action_receipt_v3 / lesson_teaching_policy_v3`。v3 仅在 learner response mode 为 Artifact 时保存 exact interaction intent、`li:<sha256>` handle、Artifact id、Artifact event id 与 sequence；none/composer 继续使用 v2 shape。receipt、Tutor message、next checkpoint/session CAS、Learning Artifact/event、conversation `item_added` 和 source Turn terminalization由同一 transaction 提交，任一 FK/CHECK/CAS/event failure 整体回滚。

Learning Item-backed Artifact owner 固定 immutable version id 与 latest published state version。materialization 必须匹配 public/content hash、Practice exercise/rubric receipt、capability set、runtime profile 和 current TeachingSession fences；表约束不允许把 Learning Item facade误绑定为 Gate/Review authority，也不产生 Attempt、score、mastery 或 progress row。

`tutor_conversation_branches` 保存一个 blocking Artifact 下的 durable depth-one branch root、predecessor branch、current event、version/round、latest disposition 与 resolved Turn。`tutor_conversation_branch_events` 是 predecessor-linked append-only CAS lineage；`tutor_conversation_branch_items` 显式记录 learner/Tutor message 与 process membership；`tutor_run_branch_scopes` 冻结 source input、branch round、Artifact、TeachingSession/checkpoint 与 closed classification/control。partial unique 与 scope FK 禁止同一 Artifact 多 active branch、nested branch、跨 conversation/user/track binding 和 item 重归属。

`tutor_continuation_intents` 保存 exact Artifact/session/checkpoint/track/progress/assignment fence、source kind/id/version、fixed priority、idempotency hash、not-before、state/version、claim owner/generation/expiry 与 consumed run；`tutor_continuation_intent_events` 保存 append-only transition evidence。一个 conversation 同时最多一条 claimed intent。claim 前必须确认没有 active foreground run、pending learner input 或 active branch，并重新验证 Artifact/session versions 与 checkpoint ancestry；stale intent转 cancelled，过期 claim按 generation release。producer 只写 intent，不创建 run或调用 provider。

branch/continuation 六张表属于 user-owned cutover target。local export 只能输出 bounded state/count/identity summary；reset/delete 按 event/item/run-scope/intent child-to-root 清理。conversation snapshot 仅在 branch history 存在时投影 v5。repeat bootstrap 必须保留早期 fragment 110 对 persisted `tutor_conversation_event_v3` row 的兼容，否则 schema 120 之前会因 projection-version CHECK 失败。

### 2026-09-13：Branch authority retirement

增量 fragment `210_tutor_branch_supersession.sql` 增加 branch `superseded` 终态、`superseded_by_session_id` 与 `superseded_at`；它不表示正常答疑完成，`resolved_turn_id/resolved_at` 必须为空。旧 `active/resolved` 行不被迁移改写。`authority_superseded` 是 append-only branch event，保存 `superseding_session_id`，不带 source input、provider response、disposition 或 assistance receipt；已有事件类型仍必须拥有完整 source input。

TeachingSession owner 在一个 caller-owned transaction/savepoint 内阻塞陈旧会话、建立真实 successor、调用 branch owner 追加事件并推进 branch CAS。数据库与 owner 都验证直接 predecessor、相同 user/conversation/track/knowledge、不同 authority snapshot、旧 session 已 blocked 且没有未终态 run；终态 root 不可再改。branch round、items、旧 disposition、Attempt 与学习进度均不重写。Python/SQL active-branch guard 不放宽；旧 Artifact 的内容保持不变，生命周期退役遵循下节独立合同。

历史修复必须使用明确范围、有限且无环的 predecessor 链，先只读 dry-run，再核对当前 authority 与预期版本，通过 owner 处理；不得直接 UPDATE 状态或顺便调度陈旧 intent。local export 保留新的 retirement identity/timestamp，不把空 source input 补成旧 learner/Turn 来源。

### 2026-09-15：Blocked TeachingSession Artifact retirement

增量 fragment `230_artifact_authority_supersession.sql` 不改写数据。正常 TeachingSession open 在 conversation lock 和同一事务内，仅沿同 user/conversation/track/node、最多 32 层且全部 blocked 的祖先链，通过 Artifact owner 将最多 64 个非终态旧工件置为 `superseded`。正在运行或有未终态 Attempt 的工件必须先完成或取消，不可退役绕过。重复 open 不增加事件或版本。

数据库的历史例外仅允许 `pending/ready/active → superseded`、version +1、清空 actions 并设置 terminal timestamp；其余冻结字段必须逐项保持不变。它要求真实且匹配当前 track/plan/progress/assignment 的 successor、同范围 checkpoint；教学 owner 的冻结 session version 对照原 checkpoint 而非已经 blocked 后的新 version。Gate/Review owner 保留身份和范围，退役不要求其可变版本仍为当前版本；Learning Item 仍校验原 published receipt、Practice materialization、kind 和 difficulty，Turn/Attempt scope 不豁免。

deferred constraint trigger 在 COMMIT 验证对应版本、scope、确定 event key、predecessor/successor 及 reason code 的 append-only terminal event。缺 receipt、篡改题面或冻结 owner 的直接 UPDATE 均失败。正常 owner 同时发布 conversation `item_updated`；退役不生成 Attempt、score、mastery、进度或模型调用。

## 2026-09-01：Terminal execution result projection

本增量不增加新的业务 authority 表。`tutor_execution_jobs.result_json` 对新完成 job 保存 strict `safe-execution-result-v2`；历史无版本 v1 row 继续由 reader adapter 转成 v2 `presentation=none`。`tutor_exercise_attempt_results.safe_feedback_json` 保存同一 learner-safe v2 JSON，Attempt result hash、outcome、score 与 policy 仍由 Gate/Review scorer authority 生成。

每个 terminal Artifact-linked Attempt 通过现有 `tutor_learning_artifacts / events / references / attempt_links` 投影：source Artifact 追加 exact `execution-result:<attempt_id>` owner event；result Artifact 使用 deterministic `execution-result:<attempt_id>` creation key，固定 `artifact_kind=test_result,purpose=result,state=completed,blocking=false`，并引用 source Artifact 的新 version 以及 exact Attempt result hash。该 durable result row 在评价 Turn 完成前不进入 conversation timeline；Turn terminal transaction 先追加 Tutor Markdown message item，再追加 exact result Artifact item，二者同事务提交或回滚。repository 在重放时同时验证 source event 与 result Artifact；只存在一侧视为 partial persistence 并 fail closed。多个 Attempt 保留独立 result Artifact，source Artifact 只投影最新 Attempt。

result-evaluation 复用 `tutor_continuation_intents`。intent 的 Artifact 是 result Artifact，source ID/version 是其 exact created event，idempotency key 为 `result-evaluation:<event-id>`；调度和 Teaching context 重新验证 user/conversation/track/knowledge/session、Artifact kind/state/presentation、Attempt identity 与 event sequence 后才消费。pending Attempt 不写 result Artifact 或 intent。以上写入由 caller-owned transaction 包含；provider failure 不修改或删除已提交的 Attempt/result。


### `tutor_demonstration_completion_receipts`

Append-only, user-scoped receipt for one completed `demonstration_v2` Artifact. It binds the Artifact version and descriptor hash to either exact isolated-Preview event evidence or bounded visible-clock evidence. The table is purge-aware, exported only as a redacted summary, and is not an Attempt/mastery/progress authority.

## 2026-09-02：Knowledge Check receipt authority

schema fragment `180_knowledge_checks.sql` 新增 user-owned append-only `tutor_knowledge_check_response_receipts` 与 `tutor_knowledge_check_assistance_receipts`。response 每 Artifact 最多一条，绑定 exact user/conversation/track/knowledge/TeachingSession/checkpoint/Learning Item/Artifact version、closed response kind、response/result hash、outcome、assistance kind 与 scorer policy。数据库 CHECK 只允许 `outcome=correct AND assistance_kind=independent` 标记 independent mastery eligible；direct-answer response 固定为安全 marker shape，不保存公开答案 authority。

assistance receipt 对每个 Artifact 的 H1/H2/H3 与 direct answer 分别 exactly-once。scope trigger 要求 Artifact 仍是 exact active/ready Learning Item knowledge check；普通 UPDATE/DELETE 以 `23514` 拒绝，transaction-local user purge 才允许删除。通用 trigger 必须先按 `TG_TABLE_NAME` 分支再读取 response 表专属字段，避免在 assistance trigger record 上解析不存在列。

两张表属于 cutover target，并进入 local summary、安全 export、reset/delete 的 child-to-root 顺序。fragment 170 提前兼容 additive `request_direct_answer` action，fragment 110 继续在 schema 120/180 前接受 persisted `tutor_conversation_event_v3`；显式 bootstrap-twice 回归验证既有 v3 row、default 与 v1/v2/v3 CHECK 均保留。


## 2026-09-02：对话内模型审查 Artifact receipt

`190_model_review_artifacts.sql` additive 扩展 Learning Artifact presentation kind，使
`model_code_review_v1 | model_code_review_v2` 同时可读，并把 presentation JSON 上限提高到
196,608 bytes 以容纳 server-built code/diff line map。早期 `120_learning_artifacts.sql` 与
`170_teaching_demonstrations.sql` 已提前接受 v2 kind，保证已有数据重复 bootstrap 在抵达 fragment
190 之前不会暂时违反 CHECK；`110_thread_turn_codex.sql` 继续接受持久化
`tutor_conversation_event_v3`。

`tutor_model_review_artifact_receipts` 是 user-owned append-only private authority，一条 Artifact 最多
一条 receipt。复合 FK 固定 artifact/user/conversation/TeachingSession/track，普通 FK 固定 exact
Learning Item version 与 Practice exercise version；trigger 在 insert 前锁定并复核 active/ready v2
Artifact、knowledge/checkpoint/owner/version/materialization。表保存完整 submission JSON/hash、verdict、
outcome/score、assistance、safe feedback、result/remediation/policy/receipt hash；CHECK 要求 failed 必有
`li:<sha256>` remediation、passed 必无 successor，submission schema/hash 必须匹配 presentation。
普通 UPDATE/DELETE 由既有 Artifact append-only guard 拒绝；只有 transaction-local user purge 可
child-first 删除。

该表进入 exhaustive cutover target inventory、本地 summary count、safe export 与 reset/delete。export
只列 scope、verdict、outcome、score、assistance、successor、policy 和时间；省略完整 submission、
safe-feedback body、presentation/submission/result/receipt hash、private rubric/test/proof。删除顺序在
Artifact event/root 之前清理 receipt，不能因新增 private child 破坏 confirmed reset。

## 2026-09-02：SQL Learning Workspace Attempt owner

`200_sql_learning_workspace.sql` additive 允许 `sql_workspace_v1 | sql_workspace_v2` presentation，
为 `tutor_exercise_attempts` 增加 nullable `learning_item_version_id`、FK 和 partial index，并扩展
owner-shape/`tutor_learning_artifact_attempt_owner_matches`。Learning Item SQL Run 必须是 `attempt_type=run`、
绑定当前 lesson assignment/document 与 materialized ExerciseVersion、没有 Gate/diagnostic/review binding，且 exact
Learning Item latest publication state 为 `published`。普通 Gate/Review/Teaching Attempt 必须保持
`learning_item_version_id IS NULL`。

repeat bootstrap 在抵达 fragment 200 前会重新应用早期约束，因此 fragment 100 已提前声明该列并接受后来
合法的 Learning Item-owned Run，fragment 160 允许 Learning Item source 的 `test_result/purpose=result`
投影，fragment 170/190 提前接受持久化 `sql_workspace_v2`。fragment 110 的
`tutor_conversation_event_v3` projection-version compatibility 保持不变。bootstrap twice 与 schema
manifest test 必须同时覆盖已有 SQL v2 Artifact/Attempt 和完整显式 fragment 顺序。


## 2026-09-02：Learning Artifact platform final schema reconciliation

The explicit manifest contains 21 fragments from 000_foundation.sql through 200_sql_learning_workspace.sql. Fragment 110 is the early owner of tutor_conversation_events and must accept tutor_conversation_event_v1/v2/v3 before every later Artifact fragment executes; repeat bootstrap over persisted v3 rows is a release gate. Fragments 120-200 add the shared Artifact, Learning Item/governance, branch/continuation, teaching commit, demonstration, knowledge-check, model-review, and SQL owner contracts without a second aggregate schema source.

User-owned Artifact/branch/continuation/completion/assistance/private-receipt rows are explicit cutover target state and are deleted child-first by confirmed reset/delete. Shared immutable Learning Item versions, source/publication/governance evidence, private evaluation templates, and catalog infrastructure remain in the shared allowlist. test_cutover_inventory_explicitly_classifies_every_tutor_table requires the real information_schema tutor_* set to equal the disjoint target/shared union; a new table missing either classification fails the final gate.

The source document drawer adds no table. It resolves immutable Lesson assignments/documents/source snapshots, persisted tutor_message_context_references, and current source-inspector Artifact provenance through a verified scoped read. Rollback keeps all additive rows/history and disables admission/presentation in reverse dependency order; there is no destructive down migration or invented Artifact backfill.


### 来源工件用途与兼容（2026-09-21）

Artifact purpose 闭合集合新增 `source_inspection`。Tutor 生成的正式来源工件关联真实 run/turn 与提交后的教学 checkpoint，并复用
`tutor_learning_artifacts`、`tutor_learning_artifact_events`、`tutor_learning_artifact_references`
与同事务 conversation item event，不新增独立分数、进度或发布表。
新 purpose 通过显式 manifest fragment 为既有数据库增量扩展约束；历史 remediation/source rows 不改写。
真实验收库只应用对应增量 DDL，不为验收运行完整 bootstrap/种子导入。

既有手动来源记录与创建事件保留为历史，不能修改为真实 Tutor turn；新来源与教学消息共用原子终态提交，不通过已移除的手动创建 API 落库。


## 2026-09-23：RAG 版本化语料权威（阶段 I）

`260_rag_subject_corpus.sql` 在 manifest 尾部增量加入独立语料表，不改变旧
`grounding_chunks` 的替换语义，不 backfill 既有 Lesson/Tutor 引用，也不为公开消费者切换读路径。

| 表 | 责任与边界 |
| --- | --- |
| `grounding_corpus_versions` | 固定 Subject/version、registry/policy 身份及语料哈希；维护 candidate、validated、published、failed、retired 生命周期 |
| `grounding_active_corpora` | 每个 Subject 一个 active 指针；用 expected generation CAS 更新，rollback 也推进 generation |
| `grounding_corpus_source_snapshots` | 保存语料内固定来源、trust、允许域名/版本/facet 元数据，不存凭据 |
| `grounding_corpus_documents` | 固定 corpus/source 文档身份、URL、文档哈希、解析状态与有界诊断，不存整页原始抓取正文 |
| `grounding_corpus_chunks` | 固定 corpus/document/source/Subject/version 及 document/chunk 哈希谱系；有界内容与 generated FTS/GIN |
| `grounding_corpus_events` | append-only 生命周期操作回执，绑定请求/摘要哈希与幂等身份；不存 provider 原文或任意运维路径 |

Repository 使用调用方提供的事务；不得在内部提交、另开一条业务事务或绕过状态/代际校验。
写操作拒绝 autocommit 连接，并在调用方事务内使用 savepoint；即使调用方捕获后续步骤的异常并继续提交，
失败操作的状态、事件和指针变更也必须整体撤销。空闲连接先开启调用方的隐式事务，不能让 savepoint 包装变成自动提交。
持久化 URL 元数据仅接受不含凭据、显式端口、query 或 fragment 的 HTTPS 文档位置；seed 主机须匹配声明域名。
validation/coverage summary 只允许有界标量事实和安全字段名，不接受嵌套对象、任意正文/URL/路径；JSON 数组必须满足元素类型与长度约束。
这些存储边界不代替后续抓取授权、重定向/DNS 检查或来源覆盖质量验证。
validated 及后续状态的内容快照不可原地替换；发布和回退只改变合法状态/active 指针，
不修改已发布内容。当前 active 语料不可退役；失败/退役状态不能回到 candidate。
同一 Subject 的两个并发激活必须只允许一个 expected-generation 胜者；失败操作不得遗留半条发布或回执。
相同幂等键与相同请求恢复原回执，键相同而请求不同必须冲突，不能以“当前指针已变化”重新执行旧请求。

这六表属于共享基础设施，不归某个用户所有。用户 reset/delete 和 clean-slate cutover
不能清除共享语料；用户 export 不额外导出原始来源、片段正文或内部审计回执。
`tutor_*` 域的 exhaustive target/shared 分类保持自己的命名空间，不把 `grounding_*` 硬塞入该集合。

此阶段不提供网络抓取、operator CLI、自动发布策略或公开 consumer；候选覆盖摘要也不等同
真实来源质量已验证。工程验收使用独立临时数据库进行 bootstrap twice、immutable/scope 约束、
CAS 竞争与旧读取兼容回归，不能记作真实语料准入、题目发布或完整小节通过。

## RAG 2.0 内部集成的数据库边界（阶段 I）

本轮shadow adapter、scenario manifest与demo不新增数据库表、迁移fragment或学习者状态。既有六张共享corpus表的不可变内容、append-only事件及generation CAS仍按上文执行。演示operator发布只允许显式隔离临时库；引用/预检探针使用调用方持有的只读快照，不修改active learning plan、progress、assignment、Lesson或Artifact。

v2引用兼容输出不是v1 `grounding_chunks` 外键或HTTP ingestion provenance。不得向既有Lesson/Artifact来源表写入伪造兼容行；公开来源冻结、权限与版本校验仍以原契约为准。表/manifest及共享corpus用户清理隔离回归纳入[验收计划](../qa/acceptance-test-plan.md)。

## 2026-09-24：RAG B1 受控发现持久账本（默认关闭）

`270_rag_discovery_jobs.sql` 是在 `260_rag_subject_corpus.sql` 之后的增量 fragment，不更改既有语料、fixture 哈希或公开读取路径。B1 只存发现作业与**未准入**候选：

| 表 | 责任与边界 |
| --- | --- |
| `rag_budget_authority_roots` | 默认禁用、bootstrap 不 seed 的服务端 root/delegation/policy/period/cap 配置；只读 resolver 逐字段核对 A 的当前 snapshot，缺审批/配置不得启用 |
| `rag_budget_periods` | canonical root + period 唯一行，记录可信服务端额度上限及周期截止；锁定此行后累计所有 job/profile 的预留、未知与已结算用量 |
| `rag_budget_reservations` | root/period/operation 幂等预留；尝试中及用量不明均占满预留容量，已结算按权威实际用量计费；跨 job 共享 root |
| `rag_budget_attempts` | 每一预留仅一次 attempt 身份；`started -> dispatched` 在当前权限/开关、完整服务端投影摘要、预留、lease owner+generation 下持久一次性 CAS；只有提交成功的首次 dispatch 可外呼，重启/重复调用不能再发送；不明用量标 unknown 且不因超时/失租释放 |
| `rag_discovery_jobs` | 无全局 beat 的显式作业；`owner_id + generation + expiry` 租约隔离失租写入，终态不重新领取 |
| `rag_discovery_job_refs` | actor 私有引用与共享 job 分离；**不属于 shared classification**，不能随共享 job/receipt 整体保留或导出。本人 unlink/用户 reset/delete 必须通过可信 `PrivateReferenceRemovalAuthority`，删除仅该 actor 的映射；无授权默认拒绝 |
| `rag_discovery_receipts` | 同一 job 内安全搜索结果码、响应摘要和已结算 attempt 身份，不存 query、provider 原文或密钥 |
| `rag_discovery_candidates` | 同一 receipt/job 范围的未准入 URL 元数据；只允许无凭据、query/fragment 的 HTTPS 位置；无 active corpus 外键、不得被正式检索或题库消费 |

Repository 使用调用方事务和内部 savepoint；不提交事务、不执行外呼。每次预留必须先由 A 的当前 `AuthorityResolver` 验证 actor/action/完整 demand/purpose/policy/delegation，再由可信 `BudgetPolicyResolver` 解析同一 root 的 period/cap；请求的 `RagBudgetDelegation` 只是匹配参考而非余额。operation/attempt/receipt 重放必须比对完整安全身份；冲突拒绝。作业 lease 过期后不可提交候选/终态；账本未知用量保持保守占用，后续权威对账不能由失败响应推测零消耗。四个自主开关仍默认关闭，本 schema 不启动 worker、provider 或外部抓取。

私有引用双用户反例：actor A/B 对同一公开 job 分别建立映射，A 的本人 unlink 或用户清理只删 A 的 `rag_discovery_job_refs` 行；B 的映射、共享 job、已结算预算/receipt/candidate 保留。清理入口不得因为 `grounding_*` / `rag_*` 表名前缀将这些映射盲目列入旧 Tutor cutover 的共享或全局删除集合。若用户导出引用，只能由产品层按已核验本人范围投影允许的个人关联，不得顺带导出另一 actor 映射、共享候选原文或内部审计。当前仅提供仓储清理端口，产品 reset/delete/export 接线尚未完成，不能宣称全链路通过。

本 fragment 属于 B1 代码合同，不代表真实 PostgreSQL、Tavily 费用、出口或用户清理/导出全链路已验收。B2 的暂存内容、许可及留存需要后续独立 fragment；B1 candidate URL 也绝非已抓取正文或正式教材来源。

## 2026-09-24：RAG B2 隔离候选暂存（不入正式语料）

`280_rag_candidate_staging.sql` 接在 B1 fragment 后，仅建未准入候选的捕获、片段和个人引用。它不更新六张 corpus 表、active pointer、旧 grounding 读取或公开消费者：

| 表 | 责任与边界 |
| --- | --- |
| `rag_candidate_captures` | 唯一 B1 candidate/job 的隔离捕获，真实请求链、最终 URL、原始捕获范围（none/prefix/full）、hash、保留期限及清理状态；原文仅获 exact StorageRetentionPolicy 后限量存放。`offline_protocol_only` 是离线协议证据；`live_egress_attested` 仅可由同一 concrete SafeFetcher 的一次性签名出口 receipt 在提交时消费，不代表正式准入。none 的 fetched hash 是空 HEAD 响应体，不是远端正文；prefix hash 仅覆盖精确 206 range。 |
| `rag_candidate_fragments` | 仅 full 捕获后保留结构化片段及 hash；过期/全局撤权清空片段文本并保留最小审计身份。不能供正式检索、规划或题库读取。 |
| `rag_candidate_private_refs` | 学习者/actor 对共享 candidate 的个人关联。本人删除仅 unlink 自己；共享来源事实和其他用户引用不随之删除。未经核验的私有导出不得暴露其他用户、共享原文或审计内部信息。 |
| `rag_candidate_intake_leases` | B1 结算并终结 discovery lease 后，按已结算 candidate 独立持久化 B2 摄入租约（owner + generation + expiry），不重开 Tavily dispatch。重试/失租只按候选和新代数 fencing；成功完成后不可再领取，失败保留已结算预算义务。表存在不构成抓取或保留授权。 |

`CandidateStagingRepository` 在调用方短事务内对同一候选的 intake lease owner+generation、已结算 B1 收据、完整 demand/purpose/root、当前 probe/store 权限和 exact storage grant 重新验证，捕获内容/hash/片段重新计算后才写入。网络 I/O 不在 DB 事务内，接口既不授教材用途也不验证评分 claim。过期/撤权清理原文及片段文本、保留获许可的非秘密摘要；临时文件、失败样本、队列与日志不得成为保留旁路。schema 可标记 concrete fetcher 的一次性 `live_egress_attested` receipt；离线测试及一次临时隔离出口 smoke 不能替代生产出口与保留许可审批。

共享候选/捕获不进旧 Tutor 用户删除集合；`rag_candidate_private_refs` 是私有映射，产品 reset/delete/export 需只处理当前 actor 的引用。B2 的阶段性抓取与暂存不等于正式语料准入；生产出口和 operator policy 未独立验收前保持默认关闭。

## RAG B 持久需求与默认关闭的候选政策

`290_rag_discovery_context.sql` 保存 job 的去身份化、经服务端审核的查询词与 hash；`rag_discovery_private_contexts` 保存按 `users.id`/actor 精确归属的 plan/node/revision、适读性和语言需求，`rag_discovery_actor_owners` 只能在可信身份绑定后创建，旧孤立引用不自动认领。重启按私有 context 重建完整 demand 后仍须再次核验 A 的当前 actor/action/policy/delegation；hash 和共享 job 不能单独授予外部发现。用户导出仅按本人投影 job/candidate 不含共享内容与其他用户引用；reset/delete 应同事务解绑自己的 context、refs 和 actor owner，保留共享用量事实。

`300_rag_candidate_policy.sql` 保存 operator 配置、bootstrap 不 seed/enable 的确切 policy generation、HTTPS host/path 探查与存储许可、内容捕获级别/字节和许可/保留截止。软来源偏好不是权限；公开可见也不推导全文保存许可。政策未知、过期、撤权或更改代际时默认拒绝。探查、暂存提交以及每一个 redirect 目标必须重新核对当前政策；代码已有逐跳政策与签名出口验证，但生产部署出口尚未独立验收，不能把离线规则或临时实验算作生产联网准入。`license_id` 必须来自 operator grant 并与候选暂存记录一致，而非依赖模型/网页自称。

这些增量 fragment 仅提供默认关闭的持久合同，不改变既有 corpus active、旧 Tutor Gate、公开 route 或来源正式用途审核。用户 reset/delete/export 已按本人私有引用接线；生产 live 执行与正式 C 准入仍有独立验收门槛。

## RAG B 基础 campaign 的服务 principal

`310_rag_campaign_authority.sql` 把 operator 配置的服务 actor、精确 Subject/version/facets/purpose/适读性/语言、预算 root 和周期/费用批准与用户私有 actor 所有权分开。bootstrap 只建表、不 seed 或启用服务 principal、campaign 或网络调用。签发的 campaign context 不属于 `users.id`，不可伪装用户计划；仅显式 operator 入口、当前 principal/policy/root/period/cost/开关与受支持 Subject 校验全部通过后才能共享 B1 broker/job/ledger。没有全局 beat、公开 route 或自动外部发现。持久 issuance 供重启重核，但并不等于来源正式准入或课程可授课。服务 principal 与审批撤销时，新操作必须拒绝，已发作业和不明费用仍按租约及账本处理。B2 probe/store 在此之外还要当前 `intake_approved`（默认 false）及精确候选存储政策、独立费用/网络/保留审批；撤回该位不重开 B1 已结算作业。

## RAG C 来源审核与正式语料准入（默认关闭的增量结构）

`320_rag_registered_source.sql` 和 `330_rag_source_admission.sql` 顺接 B 的 310 fragment。Bootstrap 只建表，不预置来源、准入、许可或生产开关。它们不重写既有 260 corpus 的六表、fixture-v1 内容/含义、旧公开检索或 Tutor Gate：

| 表 | 责任与边界 |
| --- | --- |
| `rag_registered_source_policies` | operator 预注册精确 Subject/version/facets/source、HTTPS URL/host/path、origin/适读性、许可/用途、保留期、最高 8 MiB 正文（来源策略可更低，历史 320 的 1 MiB 约束由 `340_rag_c_capture_capacity.sql` 幂等升级）、canonical root，默认 `enabled=false`；撤权不可复活，不能由模型 URL/公开域名推导许可 |
| `rag_registered_fetch_attempts` | 预注册 source 默认单 URL 一次性 `dispatched` CAS，独立于 Tavily/B1 attempt；350 仅允许绑定已终结原记录、精确新 dispatch/policy/root/request hash 与有效期的 operator 显式单次补充授权，旧记录不复活；同进程 dispatch owner 只提供 pre-DNS/pre-dial 两次 grant，重启丢失 permit。结果 settled 或 unknown，失去响应不得换 key 重抓、不能伪造 B candidate receipt |
| `rag_registered_source_captures` | 单次受控 fetch 的链/最终 URL/hash/许可/有界正文；真实 host 结算同时保存 canonical `transport_proof`、其 SHA-256、attestor 公钥指纹及 worker 镜像指纹（旧合成 fixture 可空，不等于生产证明）；只允许带签名出口的 live provenance，过期/撤权后清正文而保留允许的最小非秘密事实；记录本身不授教学用途 |
| `rag_registered_supplemental_authorizations` | 350 中显式 operator 单次追加请求凭据；绑定终态原派发、新派发 UUID、URL、策略/代次、root、request hash 和有效期，不复活或删除原记录，不链式追加 |
| `rag_candidate_use_grants` | 360 中 B full capture 的独立正式用途及历史保留授权，默认关闭；绑定 capture/hash、当前 B policy/generation/root、scope、许可和用途，允许单调撤权。B 暂存许可不能替代该授权 |
| `rag_source_reviews` / `rag_source_admissions` | 具体注册 capture 或 B full capture 的 exact 文档/revision/hash、lineage、适读性、质量与用途审核事实；review 与 admission 分离，失败/隔离不得准入。`immutable_history_allowed` 只有在 corpus 快照历史内容保留许可明确时才允许 link |
| `rag_source_claim_receipts` | 对 exact claim/需求/来源版本的独立来源验证事实；同 lineage 的另一篇不能假装独立。隔离执行路径没有可信 verifier adapter 时 DB 默认拒绝仅凭 handle 的 receipt；应用仍须独立验证语义和当前授权 |
| `rag_assessment_source_evidence` | 480 中新增的 private shared/operator source 签名证据，没有 learner `user_id`；绑定 capture/document、policy/generation/root、有限 profile、demand/claim/execution handle、独立 service signer、sealed terminal 与有效期。不是用户内容、公开来源列表或用户 export；per-user reset/delete 不删除共享 RAG 来源证据 |
| `rag_corpus_admission_links` / `rag_corpus_validation_receipts` | C admission 到现有 corpus source/document 的绑定及独立动态验证 receipt；现有 `CorpusRepository` 仍是唯一 candidate/validation event/单 active CAS 写者，旧 `CorpusService` 保持 fixture-only |

可信 control 通过 Unix peer UID/GID、固定镜像与当前 DB 授权验证 worker 报告，并在同一事务结算 attempt/capture；B 签名只证明拨号前的 namespace/出口规则，不独立证明 HTTPS 正文。`registered_source_retention` 在调用方事务内物理置空到期/撤权的 capture 正文；formal corpus 历史文本另须 policy 与 review 双重永久历史授权，不能把当前用途过期等同于历史许可撤销，也不能把读取拒绝冒充备份/WAL 擦除。

2026-09-25 隔离实测已完成真实 SQLite SELECT 全文抓取与留存（2,033,807 bytes）、provenance 再验、独立自动服务审核及签名回执、正式 supplementary admission 和 partial corpus 激活。自动审核仅批准 WHERE/LIMIT 两个精确片段；不是整页或主教材/评分证据资格。真实库现为 1 capture、1 review、1 admission、1 active pointer（generation=1），正式快照仅含 2 个获审片段。原 unknown 记录保留；后来明确批准的两次追加 GET 已耗尽（一次定位旧 1 MiB 大小拒绝、一次在 8 MiB 上限下完整结算）。这不授权自动重试或继续请求。实测仍限获准单页、无 Tavily、专用可丢弃数据库；该页最多支持 `route.sql` 的 `queries` facet，缺 `schema` 时完整基础资料仍 not_ready。任何生产网络、共享内容保留、用途/claim 或公开 consumer 要独立核对；真实来源已抓取也不能单独解除默认关闭门禁。


## 2026-09-28：隔离来源的单次到期刷新（420）

`420_rag_c_expired_source_refresh.sql` 复用现有 final-followup allowance 与 supplemental authorization，不新增 corpus authority、不自动授予权限。仅在同一 URL 已有前三次 unknown 和第四次真实 settled capture，且第四代 capture/policy/root/授权均到期但未撤销时，允许 operator 以 `standingpolicy.sourcefreshness.` 审批引用追加一次第五代全新 GET。新 policy/root/dispatch/request 必须独立、当前有效且最长 24 小时，来源、Subject/version/facets、URL、license、用途及历史许可不变，字节上限不扩大。原四次记录和到期时间不可改写；`dispatched_at <= fetched_at <= settled_at <= DB now`。旧 generation-3/4 检查保持原样，第六代及重复第五次派发拒绝；失败仍消耗本次额度，不能复用已过期正文或将 partial body 当作完整 capture。该结构已通过隔离测试，不代表新的真实抓取或 D 全链路验收已成功。

## Tavily 提取接入（430，用户显式授权切换）

`430_rag_tavily_extraction.sql` 增加 `rag_provider_extraction_attempts`，记录 Tavily 单 URL 的预派发、请求/返回内容 hash、格式/深度、provider request ID、可空 usage、时间及 settled/failed/unknown 终态；它复用当前 registered policy/root，派发先持久化、HTTP 在事务外、结果另开短事务结算。根资源上限不因失败重置。

`rag_registered_source_captures` 复用既有留存和准入体系：`fetch_attempt_id` 与 `provider_attempt_id` 必须且只能有一个。旧 direct capture 的 `live_egress_attested` 合同保留；新 provider capture 明确标记 `provider_extracted`、`text/markdown` 或 `text/plain`，不附加或伪造 TLS/worker transport proof。Tavily 返回的完整提取结果不等于原始完整 HTML。独立自动服务使用新的原生 Markdown 签名 profile 审核精确片段，后续仍进入唯一的 review/admission/corpus/selection/binding 权威。Schema 不开启公开消费者、不授予整页/主教材/评分资格，也不复活旧 direct dispatch。

## 2026-09-27：RAG D 草案材料选择与冻结（内部默认关闭）

`370_rag_plan_material_bindings.sql` 在现有manifest增量登记两张用户级表，不新增corpus/document/active pointer或题库publication authority：

| 表 | 当前职责 |
|---|---|
| `rag_material_selections` | 整稿scope、逐节点/用途需求与材料结果、canonical digest及幂等身份；snapshot不可变，只允许一次全空→全满的target run/input_revision关联，关联具有独立摘要和唯一target约束 |
| `rag_plan_material_bindings` | successor selection及exact draft/node/goal/purpose、文档/chunk/授权坐标；同自然键只能冻结一组canonical证据，更换retry key不能替代旧绑定 |

仓储在调用方同连接READ COMMITTED短事务核对当前草案和typed current授权receipt，重放不豁免当前授权；不接受None/boolean回调作成功。父selection只作反馈，新稿必须重新取证与选择。来源、claim与active权限仍归A/C及唯一corpus writer。

两表纳入用户数据统计与既有授权purge：binding→selection，再一致地解除目标用户session.current_draft_id引用后删除draft/session/scope/run。不能删除其他用户或共享corpus；普通业务无权改历史，reset/delete仍需既有用户授权。C已有表/记录和旧schema定义保留。

### D 追加：教材语义审查审计（2026-09-27）

`380_rag_material_semantic_reviews.sql` 增加用户私有 `rag_material_semantic_reviews`，关联精确run/user/conversation与selection handle/digest，保存parent/candidate/authority/request哈希、decision iteration/attempt、verdict/reason及可得模型usage；不保存原始提示、来源正文或密钥。

审查派发前记录 `dispatched`，完成后只允许一次结算为 `settled`；结算后不可变，未结算表示结果/用量未知而非免费。相同attempt重放不能再调用模型；usage结算与后续lease/current authorization是否仍有效分开，审计行不等于发布或append授权。append还需核对当前来源、父稿、候选哈希及匹配的已接受provider attempt。授权用户purge先删除语义审计，再删除其引用的selection；共享C来源不受影响。

本schema说明不是生产部署、真实来源资格或真实模型通过证据；实际隔离验收与非声明见D任务 `research/implementation-verification.md`。费用授权与执行核算另外遵循开发期外部资源政策。

## 2026-09-30：题库 P2 物理隔离持久化骨架（440，内部默认关闭）

新增显式fragment 440_learning_item_supply_sandbox.sql。完整DDL职责为14张shared表、22张private表及独立user epoch；权威清单位于item_supply/storage_tables.py。protected purge permit是内部维护权限，不是用户业务表。此结构只在专属一次性fixture验证，不代表已迁移默认业务库或上线供题。

| 表族 | 持久化责任与边界 |
| --- | --- |
| tutor_item_supply_shared_* | 公共matrix/policy/blueprint/slot、非私人job/evidence/proof/admission与预算账本；不存私人owner映射、原材料或内容hash |
| tutor_item_supply_private_* | 用户scope、材料/候选/版本payload、证据/proof/observation、发布引用/绑定/cache/staging、demand/result/subscription及job/预算；物理分表且复合owner/epoch/scope FK |
| tutor_item_supply_user_epochs | reset后保留的身份tombstone；不是公共catalog，也不是可重新进入学习的库存；deleting禁用epoch |

private repository绑定真实active track/revision/node并重验P1冻结scope/目标合同。私有handle使用独立opaque lip:v2 identity，hash由存储边界计算，不由调用方任意签发。来源坐标必须全空或全有，但只表示证据引用，不能代替RAG current authorization。不可变版本/事件及严格幂等冲突由DB和repository共同拒绝。

ObservationV2区分simulation/deterministic_probe/real_learner；真实观察须精确匹配session assignment document、Attempt、terminal result、plan revision、owner、track和knowledge node，不是只验证UUID非空；但P2不证明真实采集器、沙盘、scorer或用途许可已经ready。autonomous_evidence_policy_v2与旧v1审核/试点/人审隔离，旧行不回填；P2 admission仅blocked/evidence_pending，不能发布或物化。

现行export/reset/delete/cutover接入新private职责清单。reset先锁定并递增epoch、失效job/binding，再按child-to-root清payload；晚到请求或worker旧epoch不能复活，shared和另一用户保持。purge与既有owner使用同一caller事务，不自行COMMIT，rollback同时恢复epoch和payload。SECURITY DEFINER固定search_path、PUBLIC execute撤销、permit私有保护；普通session GUC不授予删除权。schema/maintenance owner是显式可信边界，生产角色grant仍需独立部署配置。

export只返回逐private表的有界安全摘要及truncated标识，不输出材料、答案/hidden tests/rubric、provider body、私人hash或lease信息。DB reset不撤回用户已导出文件或外部备份，本阶段不承诺备份清理。generation/network/v2 admission/supply四开关均default-off；P3作业运行、P4-P10消费者和RAG E验收仍独立。

P2工程验收包含49个聚焦DB/静态/竞态测试；epoch reset与active revision切换均以真实双连接双顺序验证bind/store/direct SQL，调用方rollback保持原子。该计数是2026-09-30 P2验收快照，不代替后续P3测试或完整API验收。

## 2026-10-01：题库 P3 内部运行时与累计账本（450）

在已验收440骨架之后显式增加450_learning_item_supply_runtime.sql，保存版本化参数profile、shared/private作业controls与checkpoint，以及逐资源预留/结算和system/provider/window/pool/private-user累计约束。身份envelope与append-only证据保持分离；所有新增业务表纳入storage_tables/cutover分类，私有表仍使用owner/epoch/scope复合边界，并由既有维护owner在同一事务内清理。

canonical obligation由服务端持久化blueprint或用户scope/demand重建，profile/client/job键不清预算。预留在统一锁序下检查全部维度；unknown占用保守预留，费用未知保留NULL，known reconciliation/真实超额如实记账且不能自动扩大cap。共享统计不得保存私人材料/用户hash映射；用户export只提供有界安全摘要。

450最终增加18张表（11 shared、7 private），包括tutor_item_supply_runtime_global_usage_facts匿名append-only资源事实；只保留opaque reservation/settlement UUID、sequence、资源种类和known/unknown actual，不存用户、epoch、scope、材料/hash/client key/provider body。private reset删除明细后，已发生实际用量仍计入global cap；latest unknown保持预留与已有known overage中的保守值，不把已知超额降为预留。该表纳入shared全分类且不阻止用户私有清理。

本节是内部代码合同，工程验收以B1b任务research下实际P3记录为准，不是默认业务库迁移或生产角色配置。完整P4-P10/E、真实provider与消费者仍独立。

## 2026-10-01：题库 P4/P5 私有流水线收据

新增显式 fragment `460_learning_item_supply_pipeline.sql`，不改440/450原DDL。`tutor_item_supply_private_generation_artifacts`保存严格生成request、内容source、provider/source receipt及source/content hash；`tutor_item_supply_private_pipeline_receipts`按白名单保存validation、blind_solve、review_bundle、admission_evaluation四类不可变typed报告。候选/版本仍复用P2专表，不能在只允许v1公开/私有内容的staging JSON夹带新元数据。

两表是private，不进入公共catalog；复合owner/epoch/scope/job/version FK、服务及DB current lease fence共同约束写入，`publication_enabled`恒为false。原export仅返回有界opaque摘要；原reset capability先清理新增子表，再清理440/450父表，保留epoch tombstone及匿名usage事实。B1c只bootstrap专属fixture，不代表默认业务库迁移或公开发布。

## P6 独立沙盘与执行-only资源门禁（B1d）

显式fragment `470_learning_item_supply_sandbox_execution.sql`增加private execution_intents、sandbox_runs、sandbox_observations三表。P6写入只允许精确独立`aearn_b1d_sandbox_20261001`及sandbox actor namespace，组合owner/epoch/scope/job/root/generation/profile/source身份与真实terminal JSON；Observation唯一键(source_run,scenario,attempt)，origin不可修改，模型不能输入sample/completed统计。

private reservation请求/token仅通过470改为nonnegative；零header必须有当前exact execution intent，七个非执行维度真0，execution_seconds严格正数。shared与原440/450/460文件未改，普通reserve默认仍拒execution-only；受信reserve_execution继续使用原450累计limit/账本及unknown保守结算。P4 synthetic库allowlist只加这一个精确P6库，不开放业务库或伪造live来源。

三表纳入原opaque export与cutover分类，原维护权限按observations→runs→intents→旧children删除，epoch/匿名usage仍保留，没有新PUBLIC purge授权。所有bootstrap与验收只作用于独立沙盘，不代表业务库迁移。阶段提交和结算分别commit，失败的真实执行/已知费用事实不可删改来使验收变绿。

450升级对仍存在的真实settlement与actual子行做幂等additive匿名事实迁移，不更新/删除旧账本，不把缺失维度或已丢失历史编成零。unknown中间行不能遮蔽上一known消费；降低资源/费用需显式reconciliation。profile/observation JSON键集与当前严格模型同步，数据库同时检查参数范围、timeout层级、floor/ceiling与初始化证据，不接受自算正确hash但内容非法的配置。

## 2026-10-02：独立服务的来源 assessment 签名证据（480）

`480_rag_assessment_execution_authority.sql` 已在现有有序 `SCHEMA_FRAGMENT_NAMES` 中增量登记，新增唯一表 `rag_assessment_source_evidence`，并给 `rag_source_reviews` / `rag_source_claim_receipts` 追加 assessment evidence 关联及精确 receipt/applicability/scope 字段。旧行保持 NULL，不把旧 supplementary、synthetic capture 或 candidate 执行结果回填为来源 assessment 权威。

新表属于 **private shared/operator RAG service evidence**：没有 learner `user_id`，保存由独立服务签名、当前 provenance 及实际 source oracle terminal 绑定的证据；普通证明字段不可变，仅有受控单调撤权。当前 SQL 写入仍限明确的 B1d 隔离库，expiry/revocation、用途、来源 current authority 和 service pin 必须分别核验；建表、FK/hash 或分类清单本身不能证明真实签名/来源/准入已通过。

分类沿用 `tests/grounding/test_rag_c_inventory.py::_C_SHARED` 及其既有 RAG exhaustive inventory，不新增另一份业务表 manifest。该集合与 `CUTOVER_SHARED_TUTOR_TABLES` / `CUTOVER_TARGET_TUTOR_TABLES` 均保持无交集；不能因为它是 shared 就加入 Tutor cutover shared、用户 purge 或全局来源删除列表。用户 export/public API 不输出该表、signed proof、source terminal 详情或 operator 审计；per-user reset/delete 只处理既有用户私有引用，不删除共享 RAG 来源和证据，也不产生公开读取授权。480 的首次 PG bootstrap/replay 与真实 reconciliation 由 main 独占执行，此文是结构/分类合同，不代表 PG 或 actual source/admission 验收结果。

## 2026-10-02：候选 admission 私有完整事实（481）

`481_learning_item_supply_admission_facts.sql` 新增 `tutor_item_supply_private_admission_facts`，由现有有序 manifest 增量执行。它是 user/epoch/scope/job/version/generation-artifact 精确绑定的 **private** 表，`payload_json` 保存 source、候选目标 coverage mapping、task ambiguity 等完整 typed receipt；可能包含 goal/draft opaque references、独立执行事实及内部上下文。`publication_enabled` 恒为 false，候选 mapping 不等于 published inventory，不创建第二个正式成绩或 Gate owner。

新表只在 `storage_tables.py::PRIVATE_TABLES` 登记一次；现有 private export 和 cutover target/count SQL 从该 tuple 自动派生，不复制 SQL、不加入 shared catalog。用户 export 仍是既有 bounded opaque ID/scope/time inventory（可据此计数），不读取 `payload_json`、goal/draft 细节、hidden datasets 或 terminal private stdout，不另加 raw 事实导出。历史 `P6_PRIVATE_TABLES` 仅表示470的三张执行表，后续481 facts仍由完整private集合覆盖。

reset/delete 沿用现有维护 owner 与 reset-permit：481 的复合 generation-artifact FK 使用 `ON DELETE CASCADE`，parent 被授权清理时级联删除其当前用户事实；epoch 与 immutable('private') trigger 仍生效。不添加新的PUBLIC purge权限或单独强制删除入口，不提前删除共享 `rag_assessment_source_evidence`、来源/corpus或其它用户数据，累计资源事实与 epoch tombstone 保留。首次481 PG bootstrap/replay及实际cascade/reconciliation由main独占；静态分类/manifest通过不能代替该真实验收。

## 2026-10-02：Python exact canonical assessment source（482）

`482_rag_python_canonical_assessment_source.sql` 保留480原片段，仅增量更新既有来源证据的profile约束及guard；不新增表，不改变shared/private分类、用户export/reset或PUBLIC权限。`python-sum-print-source-v1`仍绑定原exact URL `https://docs.python.org/3/library/functions.html`；新增`python-sum-print-source-v2`只接受canonical URL `https://docs.python.org/3/builtins/functions.html`上的**全新、当前有效registered capture**，Subject仍为`route.python`、facets仍为`fundamentals`。SQLite v1合同不变。

旧Python URL的301不能作为自动redirect许可、URL别名或旧capture转换；不改签旧proof、不续旧grant/policy/root、不复活failed/expired dispatch。有限sum/print source oracle units、独立service签名及pin、完整provenance、用途/expiry/revocation、owner/隔离库和current authority fences全部保留。482 bootstrap/replay成功只证明结构可重复部署，不代表新URL capture、source proof或assessment admission已产生；这些真实前置仍须独立记录。

## 2026-10-03：已结算来源的有限新捕获授权（484）

`484_rag_c_settled_second_fresh_capture.sql` 复用既有 `rag_registered_final_followup_allowances`、supplemental authorization 与 dispatch；只追加 nullable、不可变且互斥的两种精确 capture/failed-authorization 坐标及 FK，不新建 capture 或预算账本，bootstrap 不发授权。

- Python 分支：精确 canonical Python 官方 assessment 范围，第一次 attempt 为 unknown、第二次为 settled 且来源自然过期；两次历史 policy generation 实际均为1，不能把 attempt 顺序当 policy generation。允许一次独立新 generation=3 root/policy/allowance/auth/dispatch，保留原已消费和过期事实。合法 unused-grant correction 的前置撤销链仍须验证。
- SQLite 分支：精确 SQLite 官方 assessment 范围，原 settled capture 自然过期，随后 ordinary supplemental 为固定 PID namespace 部署错误的 terminal unknown且无 capture。新 generation=3 仅为一次明确批准的部署纠正；source_handle 继承失败 second policy，原 source 的语义范围不得扩大。零 wire 不能把旧 grant 变回 unused。
- 两分支均复用 original attempt 行锁及 allowance/auth/dispatch 三处 SQL guard；等待锁后重读数据库时间，核验 exact capture/hash、完整历史、license/usages/Subject/facets、scope 非扩大、新 root/current/expiry 及24小时上限。新 nullable 分支不能被当成旧400/410/420 unknown链继续续抓，旧分支保持原语义。
- 新字段仍是私有 shared/operator 来源治理证据，不加入 learner export，不形成 public consumer authority；旧 unknown、费用、期限、签名、capture 和 immutable history 不重写。新 GET 后仍须独立 source oracle、签名、用途准入、corpus/current binding，不因发 grant 或建表而宣称 E 通过。

## 2026-10-02：来源 assessment 的冻结需求坐标（483）

`483_rag_assessment_demand_coordinates.sql` 增量把来源签名证据唯一键改为 `(capture_id,demand_hash)`：同捕获、同冻结需求仍不得重复签发；新需求可在原捕获及政策仍有效时独立执行、签发。来源 review 保留无 assessment 关联的 legacy capture partial unique，assessment 路径使用 `(registered_capture_id,assessment_evidence_id)` 唯一关联。document/evidence 的其它唯一约束、原不可变与用途/expiry/revocation guards 保留。没有新表、预算根、公开授权或用户清理权限。

capture-only verifier 在多证据时必须 fail closed；明确 document/claim/evidence 的读取仍精确核验。不得使用任意第一条证据，也不得修改旧 proof/grant 的有效期。真实 bootstrap/replay 与新需求独立源事实证据保存在当前隔离任务，原两份 proof 未被改写；这不等于候选审核或公开供题通过。
## 2026-10-03：原生公开课程的有限 Python 来源证据（486）

`486_rag_public_python_course_source.sql` 不新增表、预算或发布许可，只在既有
`rag_assessment_source_evidence` 中增加 `python-state-source-v1` 与
`python-binding-source-v1` 两个闭集 profile。只接受 Python 官方 reference
`simple_stmts.html` 的当前真实 capture、`route.python` / `1.0` / `fundamentals`
以及原生 `course.*` / `target.*` demand；仍须应用层独立 service signature、实际
sealed execution、逐源码片段审核、C admission/current corpus 和消费 fence。
这不是把旧私有 DraftScope 改名为公开池，也不授予第三方教程 assessment 权威。

为允许包含后续 profile 行的完整 bootstrap 重放，482 的历史子集 CHECK 采用
`NOT VALID` 过渡态（新写仍受约束），486 在同一 bootstrap 中恢复并验证完整闭集。
真实新 profile 行存在时重复完整 bootstrap 已验证，已有证据/预算/当前指针未改写。
消费 actor 根据 profile 推导，不给旧签名 payload 添加默认字段；数据库 clock 的
时区表示统一到 UTC，不能据此延长旧签名或来源保留期。SQLite 的新课程闭集尚未接入。

## 2026-10-03：C corpus 按用途分区的联合快照（487）

`487_rag_corpus_usage_partitions.sql` 扩展既有 validation receipt，不另建 corpus
或发布系统。`dynamic-c-purpose-v2` 在同一快照内保留各文档独立的实际准入用途：
第三方 `main_teaching` 与官方 `assessment_evidence` 不能互相升级。每次审计仍检查
全部文档的当前来源、审核、policy/root、字节和精确片段；消费资格仅返回目标用途的
文档和覆盖范围，缺失用途不变成 ready。

新 receipt 的 `audit_policy_version` 明确区分合同；v2 的
`review_policy_generation` 为 NULL，因为各 policy generation 由身份绑定的摘要
逐项记录，而不是伪造一个 corpus-global 代数。旧合同继续非空正整数，旧记录补充的
默认审计标记是 `dynamic-c-v1`，不改写其用途或来源证明。INSERT guard 绑定已验证
corpus 的实际 policy/summary；既有 immutable guard 和唯一 active CAS 不变。
实际包含新 v2 receipt 后完整 bootstrap 两次、当前读取和禁用来源强制回滚已验证。
第三方片段 attribution 和域分离 service 签名是独立当前证据，不是公开发布许可。

## 2026-10-03：原生 SQLite companion 来源与 shared 生成暂存（488–489）

> 后续2026-10-09新增508 shared调查侧表的登记状态见本文末尾；不改变488–489历史片段或已安装状态。

488 在既有来源证据中增加封闭 SQLite predicate/order profile：primary SELECT
加两个必需的 expr/corefunc typed companions，分别固定 capture、外部 provenance、
policy/root、完整断言和期限。新子类型参与签名；旧 prepared 不新增默认字段，不续旧
签名。486 历史子集 CHECK 采用过渡 NOT VALID，488 最终完整闭集 validated。真实三
来源 prepare/oracle/sign/persist/corpus/current material 与 companion 禁用回滚已执行。

489 新增 `tutor_item_supply_shared_generation_artifacts` 和
`tutor_item_supply_shared_pipeline_receipts`：原生 public P3 job/root/lease 下的
append-only confidential staging。没有 learner owner/private scope/demand locator，
不进入用户 export/reset；也没有提前写 item bank version、publication 或 ready。
已注册 manifest/SHARED_TABLES，历史 P3 table family 保持不变。实际 bootstrap 首次
IF/CASE 语法失败已保留，仅加表达式括号后重跑成功；真实 shared provider/admission/
publication 仍是独立的后续验收，不能由两个表已创建推定完成。随后真实生成暂存的
三条原生候选见下一节；这不等于 shared publication 已通过。

## 2026-10-03：原生 shared validation（490）

490 新增 `tutor_item_supply_shared_validation_preparations` 与
`tutor_item_supply_shared_validation_evidence`，均归 shared confidential staging，
不纳入用户私有 export/reset。不可变 preparation 固定原生 artifact/item/version、
实际 public job/root/lease/profile、完整 spec/input 及资源计划；evidence 保留真实
terminal audit、验证结果和已结算使用，不从 JSON 恢复 runner 权威。既有 P3 table
family 仍是原来的12表，新表单独追加到 `P7_SHARED_PIPELINE_TABLES`。

执行型候选通过原 P3 累计预算 owner 预留，仅精确 current preparation 能使用零
HTTP/token 的 execution-only header；实际容器运行前提交预留并结束事务，结算先
独立提交，最终来源/租约检查后再写 typed validation。静态 KC 无 execution
reservation、terminal 或虚构使用量。只有真实 `machine_verified` 推进 validating，
不产生 final admission facts、publication、coverage、ready、Attempt 或 Gate。

主代理已实际生成并暂存 Python state、SQLite predicate、KC 各一条，再分别完成
9/15/0 个真实 OS terminal 的验证路径，三条 typed validation 均已提交。三个 native
version ID 仍未插入 `tutor_learning_item_versions`。490首次安装成功；含新行的
一次完整 bootstrap 已提交且8表内容 hash 保持相等。随后只读 bank 查表名错误
`42P01` 已保留并纠正，仅补做只读 readback，没有再次运行 bootstrap 或候选测试。


## 2026-10-03：原生续行、V2导入与发布（491–494）

491 新增 shared candidate continuation：只采用原已提交 generation 的数据，保留其
原job/profile/author/source，不把旧runner或验证seal恢复为新授权。新操作使用同canonical
root下的新有界lease/profile。完成guard仅对真实adoption以其余六个真实stage替代原生成stage；
private/普通七stage路径不变，不写伪generating checkpoint。

492 为原题库validation新增显式V2 provenance。旧V1通过位及policy/hash唯一性由V1
partial indexes保留；V2以exact shared validation receipt区分操作（静态KC可相同payload
但不同current provenance）。恢复导入只可复用原合法machine_verified initial event，不能
重开quarantine/published。新版本继续使用原li命名空间与原import/event owner。

493 新增shared confidential `tutor_item_supply_shared_admission_facts`。签发必须由同连接、
同Settings且V2 flag启用的原validation/review owner与原runner/ambiguity实例验证，实际
stage先提交；保留review aggregate UNKNOWN，不把一题target proof升级为2/2/1或族独立性。

494 新增shared `tutor_learning_item_native_publication_proofs`，在原事件链增加明确native_v2
policy分支，不伪造V1真人pilot/review。proof、原Practice materialization及published事件在
同一caller事务原子生成；新增nullable无默认/无回填的materialization.native_publication_txid
绑定受guard保护的top-level transaction marker。savepoint xmin不能与顶层txid等同；旧V1行
保持NULL。其他stage committed-before的xmin比较仍不普遍覆盖同父事务savepoint，实际链
按独立commit运行；不声称已验证该更宽边界。

main已在显式B1d内部库应用491及492–494，492–494保留37表原列内容hash。KC首条实际
native发布/物化通过，Python首条真实review因material_review_failure隔离且无发布。SQL单独真实
链随后发布/物化通过，fresh连接核对两条原子发布与Python无发布；完整供题尚未通过。
全部结果以当前任务runtime证据为准。当前查询另行核对source/claim/corpus、
最终published事件及code/SQL真实runtime health，不能以历史producer lease/旧facts有效期
充当当前消费许可。裸旧selector排除native。没有公开release、Gate/Attempt或完整库存ready授权。

## 2026-10-06：原生曝光与预留（495）

495增加六张user-private曝光表：births、inbox、events、watermarks、reservations、deliveries，完整表名以 `NATIVE_EXPOSURE_PRIVATE_PURGE_ORDER` 为准。真实users新增产生epoch1完整起点；既有用户、reset后的epoch或未映射origin不能以空记录宣称未曝光。原artifact、assistance、attempt、hint与Gate binding owner触发器记录不可变inbox，Gate binding本身不是展示事实。

原reset在受维护permit保护的epoch推进后通过 `native_exposure_epoch_purge` 按FK顺序清理六表，不另建purge权限，不生成新epoch完整性。assessment必须先预留两个未曝光族，practice展示须当前watermark、同顶层事务delivery及当前publication/source检查；声明family hash不等于语义独立性。

2026-10-06仅在显式B1d隔离库应用495。真实DDL/幂等、rollback-only新用户birth/watermark及原reset→epoch2通过；275张原public表行数/内容摘要安装前后与回滚后不变。真实native展示、assessment预留及完整供题包尚未因此验收，默认业务库/生产未迁移。证据见题库任务 `research/native-exposure-495-live-20261006.md`。

## 2026-10-06：新课程资料的版本化有效期（497）

### 496 真实D冻结课程映射前置

有序manifest在495后加入496的user-private `tutor_item_supply_finite_course_mappings`，引用真实confirmed session/draft、active revision/node、原D selection/assessment binding以及原P3三个scope/demand。映射receipt不可变；读取重核current claim/source/runtime，不从JSON恢复授权。三个scope共用一个receipt，safe export仅输出id、NULL scope_id与created_at，不导出source/mapping JSON。

496 reset hook仅在原permit/epoch推进后删除自身receipt，与495互不引用且均早于原父表删除。2026-10-06隔离B1d真实DDL/同片重放、空mapping表下495/496原reset共存及实际safe-export查询通过，281张既有表内容摘要不变。当时actual-D finite proof、mapped/resolve和含真实mapping FK的reset仍待验收；2026-10-07的实际有限目标提交与填充生命周期证据见下方506后续记录。PUBLIC proof或旧sum/filter语义不能替代新目标来源。

### 497 新资料有效期

用户要求延长课程资料有效期；本次工程默认选择7天。`course_material_7d_v1` 仅作用新课程proof，实际截止取7天、policy有效期/保留期、capture保留期、budget delegation与period结束的最短值；SQLite另取三个实际capture的最短截止。签发采用新的v2格式和签名域，旧v1字节、24小时合同和旧行保持。

497没有新增表或改写旧proof：先校验最终488 guard精确函数体，才替换其版本门禁及原24小时CHECK为版本化检查；缺488或函数漂移拒绝。它不修改旧policy/root/expiry、一次性dispatch、job lease或90秒运行时健康期限，也不扩大484的独立24小时授权。

主代理已在B1d应用497及同片重放，281张既有public表摘要不变，8条旧assessment proof仍通过版本合同且原行不变。新七天来源授权/fresh capture/新签名proof仍待独立真实验收，不能以迁移通过宣称旧过期材料重新可用。证据：`.runtime/e-resume-20261006/schema-497-23fb62f6a97d/result.json`。

### 498 后续真实新授权与资料刷新（2026-10-06更新）

上段497的迁移快照不包含来源验收；后续498已完成真实新授权/捕获/新proof/current消费，不能继续把它们误读为当前未执行。498增加operator共享 `rag_registered_course_refresh_authorizations` 和supplemental可空显式引用，只允许本轮五个精确来源各一次新dispatch。由真实历史推导7个既有借记（含1个unknown），本轮新增5，上限12；新source-access-only roots不可作为通用搜索/provider预算，未新增预算period/reservation或修改旧cap。

五次真实捕获均settled，四次新受限容器source oracle完成，三个assessment v2证明及一个第三方main_teaching证明的实际截止均为2026-10-13 16:09:16.360356+08:00。Python内部分用途混合C generation7、SQL内部C generation4及当前material核验通过；第三方仅exact fundamentals教学充分，不提升为assessment或全课程充分。旧generation材料拒绝且历史保留。

### 499 actual-D source分支：2026-10-06历史门禁检查点

499新增签名v3 actual-D finite profile，物理profile列沿用语义存储键兼容旧486/488重放，签名payload保留新身份而不是重贴PUBLIC。prepare/persist重建真实draft_ready节点/输入代次，consume验证正常confirmed冻结计划和active user；新oracle run/probe身份阻止旧PUBLIC terminal复用；锁等待后再次核验proof截止。

该历史检查点仅通过有限离线检查与隔离DDL/同片重放，当时用户关联payload的安全export/reset/delete或合法保留政策未闭环。它不是匿名shared审计；当时actual-D v3行数为0，未执行v3签发/落库。新的public v2来源已存在时全schema两次重放通过，不能替代含v3行的生命周期验收。后续KC私有链的实际证据见506恢复记录；E及公开消费者仍未放行。

### 500 显式V3题面展示接缝

`500_learning_item_flexible_public_spec.sql` 不新增表或改写历史行。新内部helper只对request blueprint精确 `finite-public-spec-v3` 和三种既有target放宽title/instruction；其他public JSON字段完全一致，规范任务block及其start/end marker必须各一次。旧版本仍全文一致，缺失/null/错误类型拒绝。它不替代typed任务重建、参考/等价/错误解验证、盲解或六角色审核。

迁移先核对有效489+491 trigger完整prosrc摘要及属性，只替换唯一模板比较子句，保留原lease/root/预算/settlement/source/provider/hash和continuation lookup；未知baseline拒绝。新helper无PUBLIC执行授权，不是第二发布authority。manifest显式注册500，既有489/491字节保持。

2026-10-06 19:20+08主会话在显式B1d隔离库实际应用500、同片重放及完整有序manifest重放；49项SQL helper正负例（含SQL NULL与JSON null区别）通过，283张既有public表行数/内容摘要不变。证据 `.runtime/e-type-evidence-20261006/schema-500-c1b6f22ab01c/result.json`。测试仅用历史public形状构造内存参数，没有生成新候选/来源授权/审核回执，不证明真实供题或E完成。

### 501–504 原生题型证据、曝光及actual-D私有关联（已注册；隔离安装状态见下方记录）

-501新增私有content facts、relation preparations、relation batches、eligibility四表；从原493/494和496重建事实。同一原始批次ID/hash/判断时间在新曝光下保持，不重签。新execution期限和最多7天且受source期限限制的evidence期限分别冻结。
-502新增私有type exposure snapshots/reservations/deliveries三表；当前快照来自原495 collector，SQL当前校验返回完整JSON而非布尔成功。实际预留/交付要求501 capability、同事务、当前scope/epoch/watermark与截止时刻。
-503按签名actual-D v3 owner/epoch对混合source evidence增加条件私有列、关联保护和原reset/delete尾部清理；504新增私有provenance表，精确关联已有PUBLIC载体，不将私有admission写进共享corpus。保留PUBLIC来源、其他用户、capture和共享预算历史。
-原epoch清理顺序为502 `a01_native_type_exposure_epoch_purge` →501 `a02_native_type_evidence_epoch_purge` →496/495；501不对后安装的502表建立前向FK。新七张Tutor私有表纳入原inventory和安全导出；条件私有actual-D表单独按owner统计，cutover只阻止不清理。

2026-10-06 21:21+08在显式B1d隔离库完成501–504、同片重放、完整有序manifest重放及新用户空表reset控制，283张旧表按原列投影的行数/摘要保持。**整个演练强制回滚，501–504未安装**；schema初始化器新增`--rehearse`，即使未来`--execute`也先在DDL事务内完成reset控制再提交，失败不留半验收安装。证据 `.runtime/e-native-type-20261006/schema-501-504-8eacad026a52/result.json`。不把编译、重放和空表reset当成填充私有proof/bridge或真实题包交付验收。

### 505 诊断式盲解准入（显式新policy，已注册）

新增共享不可变表`tutor_item_supply_shared_generation_policy_bindings`，在原author reservation前冻结新policy与candidate/root/job/request/profile/lease绑定。属于shared metadata，不进入用户私有清理/导出，不创建新预算钱包或覆盖义务。旧V2没有binding时仍走原策略；旧候选/已经预留或生成的候选不可追贴V3。

505以完整已知函数体和属性pin加法扩展有效489+491+500、493、494门禁，核对真实绑定、V2/V3 schema、原盲解与evaluation warning一致性；未知baseline拒绝。440–504文件不修改，旧行不升级，原provider/source/lease/budget/hash/发布owner不被warning代替。

主会话2026-10-07 00:19+08完成501–505真实PG回滚编译、同片与完整manifest截至505重放、283旧表原列摘要、空表reset及函数/OID完全恢复；00:24+08用旧失败KC候选测试追贴policy，被SQLSTATE23514拒绝，旧artifact摘要和预算root数量不变，新增binding为0。均为**强制回滚，未安装505，也不是新V3填充阳性**。分别记录于`.runtime/e-native-type-20261006/schema-501-505-6b23fc787ae2/result.json`与`.runtime/e-blind-diagnostic-20261006/historical-policy-denial-42cf0025e122/result.json`。后续若505变化须重验对应SHA；不得把仅编译通过当完整题包可交付。

**2026-10-07后续实际状态：** 独立检查补齐后，主会话在原明确隔离库`aearn_b1d_sandbox_20261001`正式安装501–505，`ddl_committed=true`，283张既有表原列摘要保持不变；证据`.runtime/e-native-type-20261006/schema-501-505-888ddcaaf280/result.json`。这不是生产安装、填充私有生命周期或完整题包通过。随后通过原thread/turn cutover的dry-run→prepare→enable启用该隔离库；5个无lease/未决effect的旧queued夹具由原owner取消并追加审计，草稿/source/candidate摘要保持，未直接修改开关状态。证据`.runtime/e-fast-continuation-20261007/thread-turn-v2-enable.json`。


### 506 actual-D私有claim触发器别名修复（独立通过，已正式隔离安装）

2026-10-07真实私有source持久化触发`42702 column reference e.id is ambiguous`：503的`rag_actual_d_private_insert()`同时使用record变量`e`和局部JOIN别名`e`。新增506仅把后者改为`private_evidence`，完整pin已知旧/新函数体及函数属性；不改440–505、不放宽owner/epoch/签名/独立引用检查，不更新历史行。

本日较早阶段，主会话2项纯契约测试和Ruff通过；真实PG编译、同片重放、完整manifest截至506重放、复用保留真实签名的私有proof/review/admission/claim插入均在强制回滚中通过，结束后数据与原函数完全还原。证据`.runtime/e-fast-continuation-20261007/schema506-rollback-3be3384227b04ef38120a1f4d3cc9397/result.json`。当时506独立复核受网关403阻塞、尚未正式安装；该失败/回滚记录保留，不倒写成正式提交。

**2026-10-07恢复后的实际状态：** `native-private-independent-check-20261007.md`已追加506独立passed，接受SQL SHA256=`5856416e9a2c81ce7b2c0d9c4356260ddace1d59ce7d23f9ebbb728c874642a9`。main在`aearn_b1d_sandbox_20261001`正式安装同一506，复用保留的正确私有signed，经原`AssessmentReceiptRepository.persist`正式提交且`current_readback=true`；未新增oracle/签名。证据`.runtime/e-actual-d-native-20261007/506-install-persist-4c62a0c556984e3b9cd86475533496c2/result.json`。403不再是当前阻塞。

随后原producer的私有bridge及assessment freeze提交、原confirm_session/CAS确认（session v4）、confirmed authority与496 finite mapping提交均通过。对应同前缀的`kc-assessment-freeze-c10b3fbdce744c55aab34cb6b5537a48/result.json`、`kc-confirm-5b452a3e34c14b399bf7a33f2ad1ea3c/result.json`及`response.json`、`kc-mapping-fcf13940d4bd4ce98e145e79df14db85/result.json`及`mapping.json`。这些是该KC目标的正式私有持久化事实，不是完整题包或公开发布。

原reset/delete又在真实填充数据上分别执行force_rollback：`rag_assessment_source_evidence`、`rag_source_reviews`、`rag_source_admissions`、`rag_source_claim_receipts`、`rag_actual_d_private_provenance`各1条→0；PUBLIC和其他用户的179张保护表摘要不变，回滚后292表全部恢复。证据`.runtime/e-actual-d-native-20261007/kc-populated-lifecycle-6692cbbd7bc140e2a72842d0dd01f112/result.json`，`committed=false`；没有永久删除原课程/私有链，也不把生命周期回滚测试称为新的数据提交。

上述来源至确认/映射/生命周期恢复窗口新增provider/GET/oracle/签名均0，规划累计77和unknown金额保留；随后新候选的1次author独立记在下方，不覆盖该窗口。P7b完整题包、P8–P10/E仍未完成，生产迁移、公开release与Git收尾未执行。

### 507：505运行时RECORD/composite声明修复（2026-10-07已正式隔离安装）

新immutable campaign `.runtime/e-native-type-20261006/kc-diagnostic-v3-20261007-actual-d-1`的`practice-1`已由原author一次HTTP生成staged，原validator本地结果为`machine_verified`；首次原`commit_validation`触发505运行时SQLSTATE42846：generic RECORD不能转换为`tutor_item_supply_shared_generation_artifacts` composite，当时没有成功提交validation，也未进入盲解/六角色/发布。失败attempt `e417d025a3714b71958849be85c4a339`保留，不能用计算阶段通过替代持久化门禁；507后的续跑另记，不覆盖该历史失败。

main在`.runtime/e-fast-continuation-20261007/schema507-record-diagnosis-c6da9b73d14f4d8da6885f04459427b0/result.json`记录真实隔离PG对照：generic record失败42846，仅generation表`%ROWTYPE`对照通过，全部未提交、0provider。该诊断本身不等于修复安装；后续append-only507已完成checker离线4 tests/Ruff及main审阅：仅3处声明变为`%ROWTYPE`，其余BEGIN之后body逐字不变，未修改旧505/历史事实。

接受507 SHA256=`5cc76ad7f096eb5944a46d269b478ef3b4ca3f29d78e218feac930bd837e71a8`。真实PG同片重放、完整manifest截至507重放、292表行不变及rehearsal回滚恢复原函数/行均通过，随后正式隔离安装`ddl_committed=true`；证据`.runtime/e-fast-continuation-20261007/schema507-acceptance-6c7a29a58d1a4e658638488514a034b8/result.json`。DDL验收provider=0、新author=0。原491一次续跑已结束：复用同一题目、0新增author，continued-validation-staged.json确认machine_verified及校验回执已提交。随后盲解请求URLError，review.json为blind_solve_pending且blind/bundle均null；六角色未调用，facts/publication未产生。一次无鉴权、无推理HEAD也出现SSLEOFError，当前阻塞为provider TLS/network，不是已完成答错；不能按V3诊断策略放行。已停止新增付费调用，不重审刷通过、不改UNKNOWN或旧lease。原author known12841/2137、total14978 tokens和金额null保留，规划累计仍77；盲解请求尝试1次、六角色0次，服务端usage unknown及7请求原review预留保留；传输诊断`.runtime/e-fast-continuation-20261007/provider-head-diagnostic-20261007.json`。

### 508：原完整审核后的shared争议调查（2026-10-09仅登记，未安装）

追加 `508_learning_item_shared_review_investigation.sql`，登记于现有单一 schema manifest；本轮用户要求不再测试，因此没有执行DDL、bootstrap、数据库读写或安装，不能沿用507的历史通过证据宣称508成立。

| 新表 | 归属与绑定 |
| --- | --- |
| `tutor_item_supply_shared_review_investigation_preparations` | shared-confidential准备：原root/job/current lease、generation artifact、已提交完整review receipt、独立调查reservation、版本化输入/资源/来源期限，generated snapshot hash；review receipt及reservation唯一 |
| `tutor_item_supply_shared_review_investigation_receipts` | shared-confidential结果：复合FK绑定原preparation/root/job/review/reservation、独立UNKNOWN settlement、完整字段级分析或安全pending失败，generated snapshot hash；每preparation一条不可变结果 |

两表均为publication_enabled=false，payload有大小/schema限制，lease/root/source/profile/完整原审核/独立资源预留/已提交结算由新增insert guard及原concrete owner核验；UPDATE/DELETE使用共享不可变门禁。仅追加508，不替换440–507函数或旧行。不包含learner-private材料/owner/epoch，分类纳入P7_SHARED_PIPELINE_TABLES/SHARED_TABLES，不进入用户export/reset或新增purge hooks。

原shared commit_review只提交blind/bundle，不完成reviewing checkpoint；受控调查允许已提交完整首轮后的合法reviewing内部动作或合法investigating，不伪造checkpoint。现行续行用shared_stage_original_matches及原continuation binding对应旧artifact与当前review job，不强制二者job相同。已有终局admission/evaluation/publication时拒新增调查；调查supported/contested仅是模型分析，不能解除旧quarantine、覆盖原报告、形成新bundle资格或发布事实。

代码为默认关闭的单次调查prepare/run/settle/persist，未接公开API/worker/operator自动调用。旧profile1、调查cap0、UNKNOWN与预算窗不升级；shared修订lineage/blocker discharge/独立复审及完整P7/P8-P10/E仍待实现/真实验收。

### 509：同root修订准备与父子候选lineage（仅登记，未安装）

追加 `509_learning_item_shared_revision_lineage.sql` 并登记单一schema manifest；本轮不执行DDL/数据库验证或安装。不得以507历史通过或508静态检查代替509的数据链证据。

| 新表 | 归属与绑定 |
| --- | --- |
| `tutor_item_supply_shared_revision_preparations` | shared-confidential准备：原root/parent job/child job/parent artifact、已提交508 investigation receipt、新candidate、版本化request/context、祖先deadline；child job、investigation receipt、candidate各唯一，generated snapshot hash；mode=live_revision_pending |
| `tutor_item_supply_shared_revision_lineage` | shared-confidential父子DATA：复合FK绑定preparation/root/child job/parent artifact，新child artifact、实际作者reservation/settlement/input trace；每preparation和child artifact唯一，generated snapshot hash；mode=verified_parent_child_data_only |

两表均publication_enabled=false、不可变且payload受界；不包含learner-private owner/epoch，不进用户export/reset。509追加原root/lease/source/调查/child祖先关系、实际author request/context/resource/settlement、新artifact实质差异与typed closure约束，不修改440–508文件或历史行。

标记为revision的child不能通过普通生成忽略冻结context；修订资源在原作者预留/重验/结算中明确计入revision_rounds=1，UNKNOWN/null费用不按零释放。基础GenerationRequestV2/ProviderReceiptV2及base-v2 author协议保留，新增supplemental-context版本与实际envelope绑定，不在原strict JSON内塞metadata。

lineage只能证明父子生成关系，不能消除旧blocker或授准入。尚无历史discharge/完整新独立复审时，revision后代在原facts及SQL准入/发布入口保持failclosed，旧nonrevision不受影响。508/509均未安装/真实调用，旧profile1/cap0/预算窗保持，完整多轮与题包/P8-P10/E未完成。

### 510：修订候选独立复审与逐条款证据（2026-10-10仅登记，未安装）

追加 `510_learning_item_shared_revision_recheck.sql` 并登记同一manifest。用户停止测试指令持续有效；本轮无DDL/bootstrap/PG读写或安装，静态源码审阅不是数据库约束已运行通过。

| 新表 | 归属与绑定 |
| --- | --- |
| `tutor_item_supply_shared_revision_recheck_preparations` | shared-confidential：原509 lineage、同root/child job/candidate/artifact/source/content/profile/policy、当前lease/deadline与完整旧dispute集合；不可变准备DATA，不是可从JSON恢复的运行权限 |
| `tutor_item_supply_shared_revision_recheck_receipts` | shared-confidential：复合准备/lineage/root/child绑定，原owner签发并提交的新validation、独立blind/六审及usage证据，逐旧dispute的新证据链接与明确unsupported/pending状态；不可变、generated snapshot hash |

新表通过 `P7_SHARED_PIPELINE_TABLES` 分类传入原shared cutover库存，不加入learner-private export/reset/delete。payload受界、schema/closure/hash/原receipt关系/current lease与来源时限必须在侧表入口校验；旧440–509文件及不可变历史不修改。

新记录只说明新独立证据与旧问题的可追溯关系，publication_enabled/blockers_discharged/admission_eligible均false。509准入/发布hold原样保留；最新六审一致通过不替代具体条款级消除适配器、目标覆盖、风险验证、第二独立bundle与原final facts/publisher。508–510未安装，完整多轮与题包/P8–P10/E仍未验收。

### 2026-10-10后续实际安装：508–510（仅原B1d本地库）

用户批准真实链路优先、少量关键反例及独立静态审阅，并要求按原隔离顺序执行。首次原子回滚演练在510的`IS DISTINCT FROM CASE ... END`处失败SQLSTATE42601，未提交；保留`.runtime/native-multi-round-live-20261010/schema-05bafe7bf7ed/result.json`。仅补齐标量`(CASE ... END)`括号后，main在`aearn_b1d_sandbox_20261001`完成同3片真实编译、重复执行及回滚恢复，然后原子正式安装，`ddl_committed=true`。证据`.runtime/native-multi-round-live-20261010/schema-b0ef4123985d/result.json`及before/after行/函数摘要；既有292表行及原函数完全保留，新增6空表后298表，无provider/GET或其他业务库变更。

已安装hash：508=`388254dca02ede33b7a0bc616f47f06c3321802795d8d78a1ca9ef4bf6c8f700`；509=`20249cf0d783472f8adabcca12916a3188565135d022a189865312313016e4b7`；510=`0ba8206fcb0493801a4099f60ee07848eeaf3a2dc698cad7c8fe0a93c014451c`。这三个片段从此作为已部署历史，后续SQL窄修追加编号，不原地改写。此次没有重跑完整manifest/旧自动测试矩阵，也没有填充新调查/lineage/recheck回执；安装不是数据链或全面blocker discharge的验收。509准入/发布hold保持，真实新候选及后续范围另记。

**随后真实首轮数据状态：** 新KC candidate06cd2062-1a79-4366-b01e-6a67026bcf29、artifact6dc5b7d5-f18e-4329-b9f2-18e36ef44874由原owner生成并提交；validation/blind/review各1typed回执，blind passed、六角色high/61440批准，main回读reviewf0d1f533-bfdc-4f9e-8c10-5eed6b1c8092的完整payload与实际私有证据一致。0实质争议，因此508–510分支的6表仍为0行，不把未走分支写成通过。真实旧expired lease在原refresh_lease受控rollback中被LEASE_STALE拒绝且control行hash保持，0provider。证据`.runtime/native-multi-round-live-20261010/kc-real-20261010-1/main-readback-summary.json`；没有新增admission facts/准入/发布或learner状态，完整多轮/E仍未完成。

**同日执行型续行数据：** SQLite新artifact39a15646-f311-4d58-95cb-5da9ec408332/version797c0917-e72b-5e58-9fc4-61b1c29697b7与Python新artifactbdefd5a4-0f20-4c20-b1a7-cf56e04472b9/versionb4b2eec1-57ba-59f4-a519-d0a4df29e2fb分别提交validation/blind各1typed回执，machine_verified/blindpassed；technical原审核gate拒绝使两份完整review receipt均0。二者没有508/509/510准备或回执，6分支表仍空；每新版本admission_facts/evaluations/publication_events均0。既有4canonical roots不变，旧KC/预算窗/UNKNOWN等14组原行仍全部存在且一致。仅原owner追加正常新campaign limits及各既有根window，无新DDL/安装片修改/旧时间改写。证据为task research/live-executable-progress-20261010.md及`.runtime/native-multi-round-live-20261010/{sqlite,python}-real-20261010-1/main-readback-summary.json`。不能以执行验证/盲解通过宣称完整六审、多轮或公开发布验收。

### 511–512：受控反例审计与持久拒绝门禁（2026-10-10原B1d实际安装）

用户明确允许一组受控反例验证分支。511追加两张shared-confidential不可变表：`tutor_item_supply_shared_controlled_counterexample_preparations`（作者预留前的实验context/request/source/profile/lease标记）及`..._receipts`（原作者实际输入trace/源结果/已提交结算绑定），不含learner owner/epoch，不进入learner export/reset。标记仅DENY/DATA，不授来源、模型、回执或发布能力；原parent及ancestry后代的facts/evaluation/nativeproof/publication受持久hold。

511选片真实rollback/replay/install通过，原298public表行/227public函数/触发器保持，新增2空表共300；hash `a4c029819c574caf5ed850dd18542d8237af2e598d2a41028d9450530729f48c`。首个实际marker插入仍在作者调用前触发UndefinedColumn：guard的`control_row%ROWTYPE`是shared_job_controls，却读取不存在的root_id。它属于shared_jobs，说明DDL编译不能代替lazy PLpgSQL数据路径。511部署后不原改，512仅替换`item_supply_internal.enforce_controlled_counterexample_insert()`这一错误root绑定，保留其他lease/profile/source/trace/hold谓词。512hash `e441283392efd686bf0e09820420a01505ab4a5ec07c26ca39581ac4f43bfbd0`，实际选片演练/重放/恢复/安装通过，全部300表旧行及其他public/internal函数/旧触发器不变，无新增表。

经原server验证旧setup0预留/工件/标记/trace/结算后，唯一同case准备恢复保留旧result/once/审计；原API取消未预留作业再创建新原job/profile/lease，同candidate/root/原unusedwindow，不延长旧profile/deadline或洗UNKNOWN。实际511prep/receipt各1：231918e6-30f7-4291-9a2c-019f2e76cc41。新artifact8e376d74-fb26-4d61-800d-0d4115397561/versiond85c89a0-9f48-5537-8297-c30f51bdedb2，validation/blind/fullreview各1；完整6角色bundle真实包含3阻塞意见，独立blind scorefalse，故停止，508–510六表仍空。facts/evaluations/publication0，4canonical roots及5687原行保持。临时rollback行形状调用实际deny函数、实际marker不可变UPDATE3个有限反例23514成立，不等于完整原facts/publisher操作或真实descendant验收。证据见task research/controlled-branch-progress-20261010.md及`.runtime/native-controlled-live-20261010/`；实验不是正常题库准入、完整多轮或semantic discharge。

### 513：第二个实质不同V2受控组闭集（同日实际安装）

最新用户执行授权在原counterexample family＋practice-1/seed0实施ONE新受控组。513只移除旧experiment-key CHECK并加入闭合V1/V2键CHECK，扩展原insert guard按两套固定context/rule/seed/program/blueprint选择，保留V1精确规则、512真实job/root修复、其余source/profile/lease/trace/settlement检查及DENY-only ancestry hold。V2完整程序来自实际option label，原allocator与finite public request仍由原owner核验；表结构/外层准备和authorreceipt不升级或授放行权。

513已由Main选片真实演练/重放/回滚恢复/安装，SHA `c449bac69ffc05220f7fa97dbd63fd1aa76e469484eea9669e5ad0aaf3bc65a8`。300表及旧行保持，0新增表；public/internal函数除目标insertguard、约束除目标closedexperimentCHECK外保持，旧trigger definitions保持。证据`.runtime/native-controlled-v2-live-20261010/schema-5b2810d06516/result.json`。508–513现均不可原改，后续SQL修复append514+。

18:48新真实进程已经原owner提交V2 marker并读回新parent held=true，证明这一preparation lazy分支实际到达；旧V1标记/作者trace/失败/once仍保留。阶段结果与后续508–510填充另记于task `research/controlled-v2-progress-20261010.md`，不因DDL/marker通过宣称全链或正常准入。

**随后真实V2数据结果：** preparation/trace9960661a-9686-459e-8fa7-71e8334b600c、artifact83df680c-59d5-45f0-9338-994d4e5ffcf2/versionee005fe5-5bdf-5f3e-810d-21c9587434af，原validation/blind/fullreview回读与实际结果一致，blindpassed且6role7majorblocking。首次真实508preparation/receipt各1：fabce18b-e424-47b2-8c0e-c323dfeac867；该receipt是调查报告证据核验失败的pending记录，reportnull，不是有效报告。509准备/lineage及510准备/receipt四表仍0，无child。Main19:20回读5831原行实例/300表、since513函数/约束/触发器、4roots保持，newversion facts/admission/nativeproof/publication0，parentheldtrue；未实际验证descendant。详见run main-readback-summary.json/main-critical-binding-readback.json，不凭已填508表宣称完整正链或解除hold。

## 2026-10-10 staged514 investigation sender compatibility (not installed)
`514_learning_item_shared_review_investigation_sender_v2.sql` is staged/registered only. It copies the original508 investigation insert guard and changes ONLY the prompt predicate to a NULL-rejecting closed V1/V2 list; no table/trigger/payload shape/admission authority is added. Deployed508–513 remain unchanged. Explicit scalar-evidence-v2 owner checks actual installed guard definition before reserve and refuses the old-only guard. No DB/DDL was executed in this repair increment; installation and row/trigger/function rollback/readback acceptance remain separate. Detailed contracts: `.trellis/spec/backend/learning-item-supply-pipeline.md`; progress: task research/investigation-sender-v2-progress-20261010.md.

### Actual selected514 install (2026-10-10, supersedes earlier staged-only status)
Main selected514 rehearsal/replay/rollback restoration/installation actually passed in existing local development DB `aearn_b1d_sandbox_20261001`. SHA244f102ea80dc841a056891654514ff0f63ea8efe43f5c9d2e744f563402f1d6; evidence `.runtime/native-investigation-v2-live-20261010/schema-7fd5e9503e1c/result.json`.300oldtables andalloldrows/otherpublic+internalfunctions/alltriggers/allconstraints preserved,0newtable. Actual current guard definition readback includesV2. This is schema acceptance only, not a new model investigation/revision/recheck or production deployment.508–514 files immutable; any next repair appends515+.

### Actual selected515 controlled repair case install (2026-10-10)
515adds only the third closed experiment key/context branch for original repair/assessment-1/seed0 and expected_slot; priorV1/V2 remainpractice-1. Main rehearsal/replay/rollback/installation passed in existing local developmentDB;300oldtables/alloldrows/otherfunctions/triggers andconstraints exceptexplicitclosedexperimentCHECK preserved,0newtables. SHA2eea258f974c3c6fe938fd7677f71159b55f616bc238057199993d135afeed2f; evidence `.runtime/native-investigation-v2-live-20261010/schema-b160ab353149/result.json`.512ancestry DENY-only hold retained.508–515 deployed immutable; repair appends516+. New V3 control preparation/parenthold actually committed before author funding, but ongoing new model outcomes are separate evidence, not schema acceptance.

### Actual selected516 revision JSON precedence repair (POST-GROUP,2026-10-10)
Actualnewgroup valid508investigation then509preparation failed22P02beforechildauthor. ActualPGcontext named public_template; readonlyJSONexpression reproduction isolatedmissinginnerparentheses before jsonb subtraction.516copiesONLY509'senforce_native_revision_insert(), correctingbothpublic_template extraction operands before deleting item_key/version; allotherguardbytes preserved. Main selectedrehearsal/replay/rollback/install passed inexistinglocalDB,300tables/allpriorrows/otherfunctions/triggers/allconstraints preserved,0newtable. SHAcd4ab9c9fa9ae7ea6d320427684a5618cf64c381b3f249d4a8ea57b9e0197ed8; schema-1c42a9bb6038/result.json undernative-investigation-v2-live-20261010.508–516immutable,nextfix517+. This is prospectiveexpression/DDLacceptance, not acceptedpopulated509/510; originalfailedgroupnotreplayed.

## 517：显式开发模型accounting-only scope（2026-10-10授权增量，安装验收另记）

新增immutable开发核算批次和作业绑定：`tutor_item_supply_development_model_accounting_batches`、`tutor_item_supply_development_model_accounting_jobs`。scope严格限定现有B1D沙盘数据库、已授权的正式配置模型/原provider/现有canonical root及当前作业profile。默认关闭，由显式原owner启用，不能由日志JSON还原调用能力。新批次生成独立当前核算窗口和32维原global分配，旧window/reservation/settlement/UNKNOWN保留；旧cap字段的正数CHECK仅作兼容核算表示，不是“无限额度”，受tagged scope的累计配额不参与开发准入。普通生产/私有预算排除这些dev-tag rows后维持原累计封顶；新批次期限仍独立有效，父子原lease/profile/source/fence和模型真实限制仍验。

绑定仅在实际新原enqueue/claim后、未预留时建立；修订child仅继承当前原parent对应账本scope，根/provider/model/期限及实际亲缘必须匹配。原reservation replay、所有32维用量写入与原UNKNOWN结算保持，用户叫停、结果/证据/once/受控hold及发布门禁不因无限累计调用放宽。已部署508–516不修改，517最小replay/rollback/history/install及有数据branch必须由Main另验；DDL成功本身不是模型或509/510通过。

517实际已于2026-10-11选择性安装，旧300表6197行实例/函数/触发器/约束保全，新增两空表；后续ONE原执行新ledger batch/job插入接受，但旧controlled preparation表的全局UNIQUE(experiment_key)真实拒绝同案例marker（23505），在作者reserve/模型之前停止。517之后302表既有6197实例及全部旧DDL保持，未追加费用事件或正式facts/发布。508–517不可再改；同案例执行身份的default-off续跑契约属于后续518+，不可无条件删除旧unique/once来放行。

## 518显式同案例执行身份（2026-10-11实施增量，尚待安装）

旧controlled preparations的experiment_key全局UNIQUE不删除。追加default-off显式case execution授权表及并行执行preparation/receipt表；case key与旧ContextV3/语义保持，新execution authorization/ID独立唯一，按当前原job/batch/profile/lease及用户单次授权绑定。并行表保留原515完整closed/source/lease/envelope/result/usage验证及额外execution绑定。只有受控DENY祖先hold查询扩展识别新marker，发布/准入不放宽；旧511–517行/约束/guard保持，旧消费once/失败不得复活。旧V7 23505/0model为历史audit，非新modelcap。注册不等于部署或模型验收，Main独立审阅及最小rollback/replay/history安装/ONE原链证据另记。

## 真实结果与事务边界窄修

ONE V8原执行已结束exit1。新execution授权、parallel marker、原author resource reservation接受（1requests/192512tokens、32globals，legacy nominal token_cap1 underaccounting_only），case/context/rule hash不变，new+oldhold true。身份/真正累计配额预留已真实验证，不是只plan标签或大数字伪无限。

模型调用前原SharedGenerationPipeline的IDLEguard报PROVIDER_IO_REQUIRES_IDLE_TRANSACTION：新增execution.verify()从原CPU issued()/original_generation()执行SQL/server_clock开隐式事务，使后来with transaction成nested savepoint，返回仍INTRANS。该安全guard正确拦下且未删除，0newmodel/0completed/0artifact/review/inv/child/facts/fees，noexpenseappend ledger145。此次授权/once和失败result/实际reservation保存，不恢复旧cap或自动重派。

Main仅两SDK文件prospective修复：verify_identity纯CPU检查enabled/exact对象identity+payloadseal/current传参/attached；issued只sameconn+pureidentity，fullDB/schema/currentledger/lease/profile/committedrow/expiry/source检查放回fence的原caller transaction。Independent窄static PASS +少量实际方法AST DATA检查noDBcall，不是重新真实验证。新SOURCE afterattempt只有这2files变，原53中51未变；原74historyfiles/oldonce/ledger145/新旧hold保持，518后305tables6235priorrowinstances/全部旧schema exact。后续新真实执行需fresh明确execution identity/once，不消费本次已用key。未Git/归档/全E/发布。

## 2026-10-11 受控execution2完整真实链结果

`519_learning_item_controlled_case_execution_followup.sql`已由Main选择安装，SHA `bc82b48fea617b5ab0463dfee6759009ae5d61621a4255dda3206d2ac1051265`：仅authorization key CHECK及原授权insert/准备scopeinsert两guard允许闭集key1/key2；旧518字节/legacy experiment UNIQUE/其余functions/trigger/constraints不改。新execution2/V9固定once与fresh原owner/profile/lease/accounting batch保持同V3 case/root/seed，纯身份lookup不得隐式打开provider IO前transaction。

真实链完成17个去重original-owner run（不是HTTP计数）：作者/独立盲解/六审/508调查/509新作者修订/新独立盲解/新六审；两原确定性validation均machine_verified。首轮4条material争议与有效4-analysis调查、native509preparation/childartifact/lineage及native510复审preparation/receipt均真实落库。新六审全approved，但4条旧争议均`unsupported/no_clause_specific_adapter`，`historical_finding_resolved=false`；无法因新审通过宣称discharge。parent/child及旧marked祖先仍holdtrue，facts/admission_evaluation/publication0，全E/Git尚未接受。

305表6309旧行与安装后全部schema定义保持，96旧历史文件保持。旧key1未结算reservation/失败/once/UNKNOWN未改；账本145原事件保持，仅追加1条至146。可观察input361315/output82742，聚合cached/reasoning/reported total/CNY及HTTP尝试数UNKNOWN。详见 `.trellis/tasks/09-22-multi-agent-item-bank-sandbox/research/real-chain-completion-progress-20261011.md`。下一增量是精确原issuer的逐争议证据适配器及后续版本化解除规则，不重跑旧suite/不刷绿/不撤销现有hold。


### 520：关系审核production-v2（2026-10-11已安装于原B1d隔离库）
520_learning_item_native_relation_production_v2.sql仅对原501的public.enforce_native_type_evidence_insert()做两处闭集版本/config/resource绑定扩展，旧v1保留。新v2严格61440/Responses/high/单HTTP/指定schema+model、原四角色和原reservation；无新表/row/hold/source/lease权威。片段SHA1dd5852f8f91b6746f49c83768ef61921a462961aaaf89e6536f310551a59295；prosrc旧5cc1858e2162073e3d5e93dbf5d68f2d639bdafedb52bc807d15ad10bff6cc4c→新204c682ae3e58565e25f9f8099500f7a96f67ddc59b5fc08229bb404f1b0927b。Main选片实际编译/重放/强制rollback恢复/安装通过，305表6603原行、其他functions/triggers/constraints不变；未验证新relation真实数据正链或P7/E。实证.runtime/p7-to-e-mainline-20261011/schema520-7c160c37a7ee/result.json。520从此immutable，后续521+先重查占号。


### 2026-10-11 SQL521 native original-consumer bridge (internal only)
521 selected B1d install is verified: two private sidecars (`tutor_item_supply_native_consumer_receipts`, `tutor_item_supply_native_artifact_bindings`), ten bounded current-owner/source/purge helpers, six trigger instances, and one exact effective230 receiver replacement. Original305 tables/6707 prior row instances, old triggers/constraints and unrelated functions preserved; selected replay and forced rollback restoration passed. Creation/ongoing action authority are separate; mode+action-bound permits do not restore historical JSON, and frozen catalog strings remain distinct. Actual native Artifact/KC delivery is pending fresh pack. 522 is registered as staged code, not installed/live; manifest registration is not full schema replay or admission. No production/public/Gate/mastery enablement.


### 2026-10-11 SQL522 normal revision new-version permission (internal only)
522 selected B1d install is verified: one shared-confidential immutable normal-readmission side table, three exact helpers/two triggers, and conditional replacement of original509 deny function only. Original307 tables/6707 row instances and all unrelated functions/old triggers/constraints preserved; replay and forced rollback restoration passed. Controlled ancestry is denied before normal permission. This is version-specific admission capability for genuinely new validated/independently-reviewed child/full original facts, NOT historical finding discharge,6bool approval or separate publisher. Positive live normal readmission/P7 still pending; old code/default holds and old510 audit remain unchanged.

### 2026-10-12 persistent pack / PRIVATE native authority (implementation pending acceptance)

Approved P7 scope adds one SHARED producer journal and nine PRIVATE responsibilities,
not a new scoring engine or a substitute approval flag. SQL523 owns
`tutor_item_supply_shared_persistent_pack_journal` and
`tutor_item_supply_private_persistent_pack_journal`; SQL524 owns PRIVATE native
`quality_evidence`, `publications`, `eligibility`, `exposure_origins`,
`exposure_snapshots`, `assessment_reservations`, `consumer_receipts` and
`artifact_bindings` (all prefixed `tutor_item_supply_private_native_`). Existing
generation, versions, source records, jobs, canonical roots and usage accounting
remain their original owners' responsibilities.

The PRIVATE journal binds ONE confirmed demand task, user/epoch, goal scope and
five stable logical item slots. The SHARED journal has only public target/work
coordinates: no private task, learner, goal/hash, private receipt or raw preference.
An initial task may explicitly adopt unchanged, freshly eligible inventory by
purpose role; a logical slot position is not a licence to rewrite an original
factory variant/full specification. Later revisions must bind the same slot,
canonical root, immutable parent and substantive child, with complete new evidence.
Journal DATA alone cannot issue a publication, pack or consumer capability.

New PRIVATE evidence/receivers must be independently closed over actual original
author, validation, blind solve, six peers, normal investigation/revision/recheck,
source/current, union exposure and consumer writes. Expired producer authority is
historical, not a standalone current-content rejection; a current owner must still
recheck source/latest eligibility/materialization/runtime/exposure. Technical phase
expiry cannot create a replacement question, task or budget wallet. Paid opaque
UNKNOWN is retained without automatic re-dispatch.

All ten tables are classified explicitly in supply storage. Safe PRIVATE export
is bounded identity/scope/time only; the two PRIVATE exposure tables have no scope
column and artifact bindings use their actual `artifact_id` key. Epoch reset/delete
must fence first, purge PRIVATE children before the task journal and original
parents, retain the tombstone, and leave SHARED/other-user/history untouched.

SQL523 is independently reviewed and **installed only in B1d** at SHA
`0f8e40c66c64e343ffe85e67b101e10105f268bdd0972506299be6c8f204307b`.
Selected compile/replay/forced rollback/install equality passed; all 308 prior
tables/rows, unrelated functions and old triggers/constraints were preserved.
Only the reviewed original native-type receiver changed and one oldtable epoch
trigger was added. SQL523 is immutable after installation. Main's actual current
five-slot adoption/idempotency/closed task receiver check passed under rollback;
its returned task ID is not a live capability or the subsequently created task.

Historical pre-install checkpoint: SQL524 was registered as staged code, **not
installed or accepted at that checkpoint**. Main compile failed with `42703`
on `x.exercise_version`; the prior smaller
snapshot's rollback PASS cannot authorize a changed fragment. PRIVATE normal,
phase and real consumer acceptance remain separate gates. Manifest registration
is not full bootstrap/replay or P7 completion. Installed 508–523 bytes, historical
failures/holds/UNKNOWN and formal Gate/Attempt/mastery boundaries remain preserved.

Latest selected installation checkpoint (2026-10-12, B1d only): SQL524 at
`ace39dd73748e68091ed55e08e7b8aae0d5c429071a4de93a0f9e96506381db1`,
SQL525 at `54140bdcac2c1aa85817efa809dad66d382d2c73f9f757b56e50059e1ab4196f`,
and SQL526 at `e7a826cfc0c7370f9a0e7a722b72846946fd262fdfb811b9a38740430055cde1`
were independently slice-reviewed and selectively installed by Main. Selected
compile/replay/forced-rollback/install equality passed; prior rows and unrelated
functions/triggers/constraints were retained. Installed 508–526 bytes are frozen.
SQL524 adds eight PRIVATE authority tables; SQL525 adds the registered-family
normal-revision receiver branch without new tables; SQL526 adds the immutable
PRIVATE enhancement-intent receiver. First-veto failure is not fallback authority.

The live persistent task retains the original five logical slots and still lacks
whole-pack readiness. Its original same-task normal-repair preparation currently
stops at original shared-candidate-continuation INSERT with 23514 before HTTP;
this is a receiver integration gate, not a reason to create a replacement pack.
Append-only follow-up receivers and actual PRIVATE/consumer/export/reset checks
remain pending. These selected installs do not establish full bootstrap, P7
completion, P8 formal Gate/Attempt/mastery, or public/production release.

### 2026-10-12 persistent normal input expression repair (534)

Selected sandbox migration `534_learning_item_persistent_normal_input_expression_fix.sql` changes only the body of `item_supply_internal.assert_persistent_normal_repair(jsonb)`: JSON extraction is parenthesized before removing allowed keys. Latest530 source/mapping checks remain intact. The migration verifies exact old/new body hashes and all original function attributes before replay, then preserves OID/owner/ACL and all metadata except prosrc. No new table, function, trigger, constraint or grant is introduced.

Actual selected compile/replay/forced rollback/install preserved318 old tables and rows plus other function/trigger/constraint definitions. Installed508–530 files remain immutable.534 installation is not authority to repeat an UNKNOWN phase: prestart proof and a same-task/root successor remain separate original-owner gates. Private evidence: `.runtime/p7-prestart-recovery-20261012/534-install-20261012T093144684397Z/result.json`.

### 542: explicit same-investigation revision successor (2026-10-13, installed)

542 narrowly updates assert_committed_revision_execution, fresh_committed_revision_matches, enforce_committed_revision_execution_insert and enforce_native_revision_insert, retaining their exact OID/owner/ACL/metadata. A separately authorized .successor.1 parent and child can use the same task/root/committed investigation; the consumed539 attempt and its known settlement remain historical. The original receipt-wide UNIQUE is replaced by two partial unique indexes: all other receipts retain single-revision uniqueness, while the one explicit receipt is unique by (investigation_receipt_id,parent_job_id). The original receiver also requires the exact registered successor parent, preventing arbitrary new parents. No new table/function/grant is added;508–541 files are unchanged.

Original TOP prepare plus original author setup, duplicate-once denial, no-HTTP enforcement and full rollback passed. The selected installation reused that successful identical-input rehearsal and preserved319 existing tables/rows and all unrelated schema. Evidence: .runtime/p7-revision-successor-20261013/542-install-20261013T080122897505Z/result.json. The later live preparation was rolled back at native_mapping_current_required before author dispatch; source_or_claim_stale was confirmed separately.542 does not renew a source grant, alter the historical source upper bound or claim revision/P7 acceptance.

### 541: original revision output durability (2026-10-13, installed)

Append-only541 adds tutor_item_supply_shared_revision_generation_outputs, internal enforce_revision_generation_output_insert() / assert_revision_generation_output_current(uuid), and INSERT/immutable triggers on the new table only. It binds the original staged output, complete generation receipt, frozen request and observed author-input to the preparation/root/job/reservation/settlement. The INSERT trigger assigns capture_txid from the server TOP transaction; the current receiver rejects same-TOP records even when inserted through a savepoint. PUBLIC privileges are revoked. Installed508–540 and all old function metadata remain unchanged; this grants no provider, admission or publication authority.

Actual selected installation passed compile, DATA guard regression in a real nested savepoint, replay and full rollback, followed by exact installation. All318 prior tables/8148 rows, old functions/permissions/triggers/constraints and the156-event ledger were preserved; the new output table was installed empty. Evidence: .runtime/p7-generation-durability-20261013/541-schema-2ec17d275c32/result.json. No full bootstrap or real-provider cross-process recovery is claimed. The old c859 revision has no durable output to consume and was not backfilled.

### 540: revision generation matches the frozen child request (2026-10-13, installed)

The first fresh539 author invocation returned a staged result and committed known usage, but the original509 generation trigger rejected insertion with23514: its blueprint operand still referenced context.parent_source.blueprint. Registered family revision v2 can legitimately use a different frozen child blueprint. Append-only540 changes only that operand to request.blueprint; NEW.request_json equality, candidate/root binding, substantive change and valid_until checks are unchanged.509 and all other installed SQL files remain unchanged; no new authority, table, trigger or grant is added.

Selected sandbox installation passed compile/replay/full rollback, then exact installation. All318 existing table contents, other functions/constraints/indexes/triggers and the receiver OID/owner/ACL/full metadata were preserved. A rollback-only TEMP trigger regression accepted the captured source against its frozen child request and rejected the parent blueprint; exact diagnostic/deadline/substantive checks excluded other rejection causes. This is guard DATA acceptance, not an artifact or lineage write. Evidence: .runtime/p7-fresh-revision-20261013/540-install-20261013T051105381539Z/result.json. No provider calls occurred during540 installation; full bootstrap and P7 acceptance remain unclaimed.

### 539: fresh committed-investigation revision execution (2026-10-13, installed)

539 adds owner-only assert_committed_revision_execution(jsonb), fresh_committed_revision_matches(jsonb), enforce_committed_revision_execution_insert(), the PRIVATE a003_committed_revision_execution BEFORE INSERT trigger, and only committed_revision_execution in the existing record-kind CHECK. No table/index/public grant is added. Only enforce_native_revision_insert() and persistent_registered_family_revision_matches(jsonb) receive the registered-case execution/evidence separation; OID, owner, ACL and remaining metadata are preserved. Legacy/default paths retain their old expiry gates.

The original TOP exercised a fresh same-root original517/P3 window, actual revision preparation/author preparation, current context and one-use refusal without HTTP, then restored all318 tables/rows/schema/indexes and ledger155. Selected installation reused that successful same-input replay/rollback and required the current DB baseline to match; it did not repeat the rehearsal. Evidence: .runtime/p7-fresh-revision-20261013/revision-rehearsal-20261013T041239245797Z/result-private.json and539-install-20261013T042522750279Z/result.json. Installed508–538 bytes stayed unchanged. Manifest now includes539, not531; this does not claim full-bootstrap or P7/public acceptance.

### 2026-10-13 persistent allocation scalar expression repair (538)

The original revision-preparation rollback test after537 exposed a fifth extraction-minus operand: (spec->'allocation'-'variant_id') raised42725.538 only parenthesizes that extraction before scalar-key subtraction, changing the same function body9a2376... to21e3c91fc8d3efb576fc456aaf17de1040e5296d66985b276e9ee610e5984ae3. All five actual JSONB subtractions in the complete function are now parenthesized.537 and older installed files remain immutable.

Actual selected538 compile/replay/forced rollback/install preserved318 tables/rows, function OID/owner/ACL/all other metadata, other schema/indexes,27 old SQL files and ledger155. SQL SHAd5c784a6840dfb9286564634df5884a9473449961644384140aee7c575749e82; receipt .runtime/p7-committed-revision-20261013/538-install-20261012T180757361325Z/result.json. Manifest includes538 after537, not531. No full original revision business acceptance/live call is claimed: the original window subsequently expired and remains closed without changing old timestamps.

### 2026-10-13 persistent registered family expression repair (537)

Selected537 is installed in the original B1d sandbox. It changes only persistent_registered_family_revision_matches(jsonb): four JSON extraction operands (spec/parent blueprint and public_template) receive parentheses before subtraction. Old prosrc8df23b08aee40c277a320efa8df047d279250944d89157342349253aad83026b becomes9a2376a15e47517a2229da3456184e2e497d9cd736dc6f7856533bf81e2e84b6. Every other expression, current-source/phase/family/history gate and function metadata/OID/owner/ACL remains unchanged. No new table, index, trigger, constraint or grant.

Actual selected compile/replay/forced rollback/install preserved318 old tables/rows, all other functions/triggers/constraints, both-schema index definitions,26 installed SQL files and the155-event ledger. SQL SHA50cdcff72db8857177d66fa5610022baba9d7ae6002add443d8f44d567a47cc3; actual receipt .runtime/p7-committed-revision-20261013/537-install-20261012T173754062551Z/result.json. Manifest registers537 after536;531 remains unregistered/uninstalled. Installation is not business revision acceptance or permission to replay an investigation/UNKNOWN.

### 2026-10-13 explicit single-attempt recovery (536, selected sandbox installation)

536 is installed only in the original B1d sandbox. It adds four owner-only SECURITY DEFINER functions and three additive insert triggers, extending the existing PRIVATE journal record-kind CHECK with `explicit_recovery_approval` and `explicit_recovery_binding`. It creates no table or general grant and replaces no old function or trigger. The permission is the registered human-approved new attempt despite retained uncertainty, not historical HTTP=0 proof or generic UNKNOWN clearance; consumed535 evidence and both old failed phases remain immutable.

The exact preparation `UNIQUE(review_receipt_id)` constraint and its backing index are replaced by `shared_investigation_explicit_review_once`: ordinary reviews retain one unique bucket; only the registered review and exact repair.frame.3 operation have a second bucket. The added preparation trigger still requires the genuine original binding/phase/job/reservation, so a forged JSON operation key cannot authorize insertion. The original reservation uniqueness and composite preparation/receipt FK remain intact; no external FK depended on the removed single-column unique constraint.

Final SQL SHA256 is `7d1d262615bcc38a1bc1d5da1c8cac3d2149ae43a4363f24f8c288bd0c129b66`. Actual original-owner TOP preparation, local seal/fence, registered stage-start, wrong-case/unbound denial, unique-index algorithm, safe export and epoch isolation passed with a forced rollback, restoring318 old tables/rows/schema, every public index and the154-event ledger; no network attempt occurred in that rehearsal. Evidence: `.runtime/p7-explicit-recovery-20261012/536-full-rollback-20261012T164016018467Z/result-private.json`. Selected compile/replay/rollback/install then passed the exact function/trigger/CHECK/index whitelist with old rows,25 installed SQL files and ledger unchanged: `.runtime/p7-explicit-recovery-20261012/536-install-20261012T165420772583Z/result.json`. Manifest now registers536 after535;531 remains uninstalled/unregistered. Installation does not establish live success, full bootstrap, P7 completion or public release.

### 2026-10-12 registered prestart recovery (535)

Selected sandbox migration 535 adds owner-only functions assert_persistent_prestart_recovery(jsonb,uuid) and enforce_persistent_prestart_insert(), plus a001_persistent_prestart_insert on the existing PRIVATE persistent journal. Only its exact record_kind CHECK is extended with prestart_proof/prestart_binding. No table, index or grant is added; no prior function or trigger is replaced. Installed508–534 bytes remain immutable. The exact registered original task/failed phase/root/revision/slot and accepted original prestart prerequisites gate a one-use successor; a proof/binding row is not an execution capability.

Main exercised the actual original recovery and investigator preparation, one-use/wrong-case denial, existing private export and original epoch purge in one TOP forced rollback. All318 old tables/rows/schema and ledger were restored with no HTTP attempts. The final raw receipt binds SQL, Python and harness versions: .runtime/p7-prestart-recovery-20261012/535-full-rollback-20261012T110905257567Z/result-private.json. Selected535 compile/replay/rollback/install then passed the precise whitelist and preservation check: .runtime/p7-prestart-recovery-20261012/535-install-20261012T111922358340Z/result.json. Manifest includes535 after534; unreviewed531 remains uninstalled/unregistered. This is not a full-bootstrap or P7/public-release acceptance.
