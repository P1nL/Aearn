# D 实施与验证计划

> 2026-09-27；用户已明确批准D实施并已start。内部实现/隔离验收完成；不commit/push/deploy。联网/真实API资源授权已于2026-09-27项目级获准；后续满足任务执行与既有安全条件后无需逐次重问；费用由用户监控。

## 工作切分与监督
当前会话主代理负责合同决策、方向纠偏、最终集成、共享文件写权和验收。子代理按2026-09-28用户最新要求统一GPT-5.6 Sol：常规实现high，授权/事务与独立复核按风险选high或xhigh；不得递归派生。每个代理只写其分配文件，保留C及其他并行改动。需共享文件时先交接，不并发改schema manifest、settings、plan/tutor入口或规格。

主代理不把关键阻塞研究整个交出去等待：先冻结合同/调用顺序/测试矩阵；并行代理分别实现证据与学习服务的独立模块。架构审查时要求可观察的实际方法调用、DB写入和拒绝结果，不以“已有接口”替代消费者。

## P0 执行前确认（主代理）
追加修复批次：按research/repair-acceptance-plan.md执行；原P0-P5勾选为前一批次证据，不能当作追加修复完成。

追加结果：语义候选审查/有界修复、每次请求预算及相关隔离验收完成；真实reviewer正反组件验证通过。真实C来源未取得，完整C+D链仍未通过，不能勾为完成。最终59项D专项、1304passed/55skip广回归及保留边界见research/repair-verification.md；无commit/push/deploy。

- [x] 用户批准PRD/design/本计划；两份jsonl均为真实spec/research；task validate通过后start。
- [x] 核对基线67个既有未提交文件hash、分支及C状态；有外部修改先协调，禁止reset/stash/checkout覆盖。已有C检查点保留，不擅自commit/push。
- [x] 检查370编号占用、schema manifest、当前plan/provider及inverse-reference测试；锁定本轮写集。
- [x] 冻结DraftScope、MaterialSelectionResult、BindingV2、purpose/status/error边界、旧反馈→successor→新selection协议。

## P1 合同与最小持久层
- [x] 新增版本化strict合同，nested重验、handle-only、bound arrays、canonical hashes。
- [x] 两张selection/binding表：selection snapshot不可变且仅一次NULL→target-run关联；binding不可变。整稿selection粒度、target run/revision唯一认领、自然键(draft,node,goal,purpose)唯一冻结、scope FK、幂等冲突、授权purge路径；schema fragment单点注册。
- [x] 专项合同/迁移测试，双bootstrap，existing-v1/schema清单兼容。共享manifest由主代理串行归并。

## P2 证据与当前授权（GPT-6 Sol，窄写集A）
候选：grounding/evidence_binding_v2.py、current_authorization.py、material_binding_repository.py、最小release-scope类型及对应tests/grounding/test_rag_d_*。
- [x] 从唯一formal corpus精确取证，复用C review/candidate grants/governance；不套fixture planner信任。
- [x] ready/partial/gap及用途、approved excerpt、当前授权、逐claim校验；缺可信resolver默认拒绝。
- [x] current-check与publication fence同conn/事务，拒绝autocommit/self-commit/旧generation。
- [x] 落盘逐writer锁矩阵：admission/policy/retention/grant/root/pointer各对应实际冲突锁或UPDATE、两种barrier先后、等待后current重读/clock_timestamp、整笔rollback断言；双连接实测，不只测pointer。需要修既有C模块先交接给主代理另派窄patch，不覆盖C工作。

## P3 学习侧真实内部消费者（GPT-6 Sol，窄写集B，与P2在P1合同稳定后并行）
候选：learning/material_selection.py与对应tests/learning/test_rag_d_*；不得直接抢写既有plan/tutor共享文件。
- [x] 需求→existing合格材料复用→反馈安全投影→模型修订请求→successor重验→新selection→冻结。
- [x] 完整节点及目标保留；existing_only不新增发现；真实job才pending，部分ready受前置依赖限制。
- [x] 模型IO不在事务内；用新planning run/input_revision，不在同幂等run强行append第二稿。
- [x] default-off零新增IO、跨用户/草案/目标/用途错误、过时回调、取消/失败、幂等测试。

## P4 串行真实接线（主代理协调的独立implement代理）
候选共享写集：learning/plan_capability.py、plan_drafting.py、plan_repository.py，必要的tutor planning feedback上下文/handler factory、learning/material_planning_composition.py、repositories/local_user_data_repository.py及其reset/delete测试；仅证明必需时改plan_service.py。
- [x] build_internal_material_planning_dispatcher通过API Settings.rag_evidence_consumer_enabled + server-only opt-in受限注入既有dispatcher/context/capability，不更换provider、不新增公共路由/DTO；普通factory、缺注入和flag关闭分别zero-call。
- [x] parent selection到target run/input_revision在provider前同事务一次认领落盘；真实context按持久关联加载，append前双CAS，不取“最新”。确定性transport驱动dispatcher→context→gateway→capability→repository新稿→新selection→冻结；覆盖重启定位、错run、竞争认领、取消/重试/旧回调。
- [x] 精确新增D import例外，旧shadow/autonomous/plan_*反向引用检查继续约束；不删扫描或全模块豁免。
- [x] 用户purge同一aearn.learning_track_purge_user_id事务按binding→selection/target关联→旧draft/session/scope→既有run清理；reset/delete分别验成功与失败回滚、其他用户/共享corpus不变。
- [x] 如果接线必须改变公开DTO、默认confirm或既有产品决策，先回规划请求批准，不悄悄扩写。

## P5 独立复核与主会话验收
- [x] GPT-6 Sol xhigh独立审查D-AC1..8、scope漂移、source/claim越权、时序、真实接线和证据等级；审查后主代理复跑受影响测试。
- [x] disposable PG串行验证，双连接锁barrier，bootstrap两次，scope内clean-up；schema/learning/grounding基线回归。
- [x] Ruff、Mypy、uv lock check、diff/hygiene；静态审计无新增公网/生产release/模型联网/管理UI。
- [x] 更新backend scoped spec和既有runtime/database/QA权威文档，按实际完成项记录；不把规划写成事实。
- [x] 报告D每项passed/failed/blocked/not_executed及遗留；真实source/provider/publication/E单列。提交/推送/归档另遵用户授权。

## 计划执行的验证命令（本轮未运行）
从仓库根用PowerShell7；先设`PYTHON_DOTENV_DISABLED=1`、`LLM_TYPE=disabled`。离线测试明确排除real_provider，不继承业务DATABASE_URL。所列D文件由实施新增，最终按实际文件名收敛。

```powershell
uv --directory .\aearn\services\api run python -m pytest -q -m "not real_provider" tests/grounding/test_rag_d_contracts.py tests/learning/test_rag_d_material_selection.py
uv --directory .\aearn\services\api run python -m pytest -q tests/learning/test_learning_plan_draft_capability.py tests/learning/test_learning_plan_revisions.py tests/learning/test_learning_plan_sessions.py tests/learning/test_rag_plan_preflight.py tests/learning/test_rag_plan_migration.py tests/learning/test_rag_plan_shadow_boundary.py tests/learning/test_rag_grounding_adapters.py
uv --directory .\aearn\services\api run python -m pytest -q tests/grounding/test_rag_material_source_contracts.py tests/grounding/test_rag_source_usage_policy.py tests/grounding/test_rag_assessment_claims.py tests/grounding/test_rag_autonomous_boundary.py tests/database/test_schema_manifest.py
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\api lock --check
git diff --check
```

隔离PG：另建本轮专用`aearn_rag260_c_d_*`本地库，先对DATABASE_URL和AEARN_RAG_C_TEST_DATABASE_URL对应连接执行current_database()并记录同一正确目标；串行bootstrap两次。不能只设变量就认定隔离，不使用C真实capture库/用户库。再跑新`test_rag_d_*`PG与`test_rag_c_*`/`test_rag_b_qualified_corpus.py`，覆盖registered和candidate授权两路；设置测试barrier避免sleep猜测竞态。真实数据库测试skip不能算通过。

API无公开DTO更改时不默认开浏览器；如必要compat改动触及DTO，先规划确认并同步Desktop解析测试。不得把Desktop构建或fixture测试当真实浏览器/模型验收。

## 验收矩阵与停止点
- D-AC1：zero-call spies + 原public/fixture/shadow快照；关闭flag在resolver前。
- D-AC2/3：gateway替身驱动真实服务/DB，旧稿→反馈→新run新稿→新selection→冻结；伪造handle、旧回调及跨scope全拒绝。
- D-AC4：已有足够/无资料/只有登记/过期/撤权/错版本与用途/部分依赖，search调用计数0（existing_only）。
- D-AC5：exact chunks/获审span/corpus摘要被替换、用途扩大、same-family/循环证据、虚构执行、resolver缺失负例；正例的synthetic信任明确标注。
- D-AC6：撤权先/后、pointer变化、expiry在等待期间发生、policy/grant/root变更、跨conn和autocommit；同事务模拟publication+materialization均回滚，非真实题库联调。
- D-AC7：重放/冲突（包括换retry key同自然键异证据）/target run一次认领/重启按持久关联读取/并发draft CAS/双bootstrap；reset/delete与失败回滚各验，其他用户与共享corpus不被意外删改。
- D-AC8：报告明确当前C真实回执过期、可信生产claim/执行resolver缺失、公开D/E关闭；真实assessment ready、item publication/materialization/供题blocked/not_executed，生产claim/执行resolver为E/owner前置；不据synthetic正例改判live。

公开新来源与已配置provider的范围内调用适用项目持续授权，不逐项再问；新增收费服务、扩预算、未获准私密数据、业务库破坏性变更或公开release仍遵相应许可边界；遇到只有fixture正例也不改变计划目标或掩盖gap。回退只关闭新composition/保留合法历史，禁止删除C工作与数据库。

## P6 有界真实资源验证（人工费用监控模式）
- [x] 使用已授权已配置provider，合理限制输入/输出与有界重试；用户自行查看账单，共享300元预算不按任务重置。
- [x] 保留实际usage/调用结果/失败/重试，未知费用不填零；不要求先开发统一计费、自动预留或硬封顶，也不宣称自动240元提醒已实现。
- [x] 范围内直接抓取公开课程资料并按现有安全/来源/用途规则核验；不复活旧C grant/dispatch或修改到期回执，不重复逐次申请。
- [x] 免费搜索耗尽existing_only，不开启付费搜索/新收费服务/充值/升级；用户叫停或已知额度耗尽即停止新增收费请求，尽力取消在途。
- [x] 真实来源、真实API、D绑定、公开发布/E验收分别记录；本授权不代替生产release，不扩D写集建设计费系统。

2026-09-27 费用策略补充：侧会话转达用户选择人工监控供应商账单；该政策取代本稿历史“先实现自动费用预留才能调用”的限制，300元总额与其他授权边界不变。

## 实际执行说明
上述步骤在获准D内部范围内执行，测试/边界以research/implementation-verification.md为准。P5不是全库全绿：保留一个HEAD运行模块可复现的上下文预算断言失败和Windows Unix-peer未执行；不声称所有writer并发全覆盖。P6只做有界真实client/公开HTTP探测，未把fetched_unreviewed材料准入或完成全真实D课程链。Phase3.4提交/推送未获本轮授权，任务不归档。
