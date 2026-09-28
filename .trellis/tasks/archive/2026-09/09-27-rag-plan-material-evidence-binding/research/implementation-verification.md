# D 阶段内部实施验收（2026-09-27）

## 当前结论
已完成获准的内部default-off教材反馈→指定新规划run→模型修订→同事务重验→successor精确binding链，以及D当前授权/publication fence接口。未启用公开消费者，未接管E全部item发布/供题入口。代码未commit/push，Trellis保持in_progress等待单独提交收尾，不自动归档。

完整D组合验收使用真实PostgreSQL、真实C仓储/当前授权适配器和确定性provider；另有两次配置的真实DeepSeek调用与公开资料获取探测。两者不拼成“完整真实课程闭环”。当前真实来源准入、真实评分claim resolver、E公开发布不在已通过声明中。

## 授权、保护与环境
- 用户2026-09-27明确批准执行D。子代理均GPT-6 Sol，implement/check用high/xhigh，主会话在当前线程纠偏与最终复验。
- 分支保持codex/rag-source-admission-corpus-governance；私有检查点 `C:/Users/32624/.codex/tmp/aearn-d-checkpoint-20260927-130825` 的101个文件逐项SHA256核验。未还原/清理C工作树。
- 本轮仅新建容器aearn-d-fixture-01a0e0c7，使用本地postgres:15镜像、--pull=never、127.0.0.1:55437，不挂载既有数据库卷。各专库均实际核对current_database()，full manifest bootstrap两遍，dotenv关闭、测试LLM禁用。
- 不同guard测试按其真实要求分库：D/C使用aearn_rag260_c_d_*，CLI/retrieval使用aearn_rag260_cli_retrieval_d_*，semantic使用隔离容器内aearn_semantic_review_20260909，catalog使用aearn_repair_d_20260927；没有放宽生产或测试隔离guard。

## 最终验证
| 检查 | 实际结果/边界 |
|---|---|
| D所有专项（schema/合同/仓储/授权/fence/清理/真实dispatcher/parent上下文） | **47 passed，0 skipped，21.89s**；最后代码版本，含terminal_outcome COMPLETED、语言/Subject不偷换、同事务parent+feedback及DB-clock fixture纠偏 |
| 较广grounding/learning/database + Tutor runtime/history | **1312 passed，32 skipped，246.34s**；固定名字semantic guard套件拆出另跑；此后最后D-only修正由上述47项重跑，不合计成去重总数 |
| 固定semantic专库三套 | **15 passed，29.27s** |
| CLI/service/retrieval专库 | **30 passed，3.83s**；此前未预bootstrap产生的UndefinedTable已按专库准备流程重跑解决，不改代码或放宽guard |
| catalog/相关artifact/teaching supersession专库 | **14 passed、1既存失败，25.57s**；见下节 |
| Ruff app tests | passed |
| Mypy app --no-incremental | **324 source files passed** |
| uv lock --check --offline | passed（55 packages） |
| git diff --check / task context validate | passed；仅既有Windows CRLF提示 |

广回归中CLI/retrieval及catalog隔离条件的skip已在对应专库补跑；Windows的真实non-root Unix peer用例仍未执行，不冒充Linux验证。不存在“全后端/所有平台/所有writer并发均通过”的声明。

## D-AC映射
- D-AC1：普通factory、开关关、缺server opt-in/依赖无新增D IO；旧v1/public路径和精确import边界回归。
- D-AC2：实际dispatcher→context→gateway→Skill/capability→plan仓储→新selection/binding，实际provider context含完整parent profile、全部node/prerequisite/hash与资料反馈；一条使用真实C EvidenceSelection组合。
- D-AC3：parent/target run持久一次认领、重启读取、错run/用户/版本/节点/目标拒绝；parent handle不授successor信任。
- D-AC4：已有资料复用、empty/partial/gap、前置main_teaching闭包、顺序无关与cycle拒绝；无资料不假ready。Python/SQL课程不得被RequirementResolver换Subject，非pilot scope不启用。
- D-AC5：实际chunk facets核验、exact当前文档/版本/摘要/用途；D仅将已核验更宽同Subject/version授权向请求子集投影，不扩大原A/C grant；缺可信claim/执行resolver仍拒绝评分。
- D-AC6：同连接短READ COMMITTED写事务、无self-commit/旁路连接；policy撤权两种先后和root锁等待跨expiry有双连接证据，其余candidate/capture/pointer等有顺序负例。**没有把代表性并发测试扩称全部writer竞态矩阵**；E仍须真实入口接线与供题再验。
- D-AC7：两张用户级表、snapshot及binding不可变/一次assignment例外、自然键冲突（换retry key也不能替换证据）、重放当前授权、合法purge及回滚/其他用户/shared corpus不变。
- D-AC8：离线/隔离/真实HTTP/真实API/正式准入/public release/Gate分层记录；C旧回执未续期或伪造。

## 已处理的主要纠偏
- 移除每节点固定版本/全课程facets/唯一主教材用途的假设；材料需求由受信节点策略生成，保留课程Subject边界。
- current授权回调必须返回绑定本次对象的严格receipt，None/bool不能放行；覆盖来自实际chunks，不信模型/selection自报。
- SYSTEM最多3项会丢D反馈和parent草案。改为有界required facts，parent完整分片按真实Builder序列化逐项等值校验；原1200字符、8项及总token限制不变，容不下拒绝，不截目标。
- feedback与parent成对同事务读取，避免并发完成run后只发旧feedback；模拟交错回归拒绝缺parent。
- 修正真实gateway的Skill选择/能力调用分轮和字符串二次JSON编码；修正production JSON-mode DTO重构、binding版本参与hash以及授权callback签名。
- 新私有receipt清理真实触发旧session.current_draft FK；在获准purge事务中仅解除该用户引用，再按child→parent删除。没有把fixture指针置空来掩盖问题。
- fixture按C的候选验证generation与active指针CAS分别使用正确值；不改生产CAS/唯一索引。PG伪回执使用数据库clock_timestamp，消除宿主/容器时钟轻微偏差导致的偶发“未来回执”。

## 真实资源与费用
详见live-validation-summary.md、real-source-diagnostic.json、两份real-provider-verification*.json。Quick Start HTTP200完整7842bytes；SELECT大页诊断只获得prefix/中止，不标full。两次真实deepseek-flash共1677 tokens：第一笔结构通过但缺口词义有歧义，第二笔修正提示后通过有界语义审查。人民币费用未知，由用户监控，不写零/不推算剩余300元。没有新收费服务、付费搜索、充值或公开开关。
这两次是client级真实修订探测，不是全真实D持久链；新抓取资料仍fetched_unreviewed，未作为主教材或评分准入。

## 已复现的既存失败
`tests/learning/test_catalog_artifact_scope.py::test_small_provider_budget_still_rejects_artifact_before_provider_or_writes` 期望TUTOR_CONTEXT_REQUIRED_OVERFLOW，实际旧路径completed。主会话在同隔离repair库以HEAD 6154746的interactive、plan_capability、local_user_data_repository模块做**仅内存加载**、不改工作树，再跑同例仍同样失败（1failed/1.45s）。这是改动前运行模块可复现的上下文预算断言差异，不是本次费用预算，不扩大D写集修改全局预算/测试预期。未称整库全绿。

## 收尾
所有implement/check/research子代理已结束。没有commit/push/deploy、没有修改受保护前端原型；只有专用临时容器与本轮公开资料临时文件会被清理，私有工作树checkpoint保留。实际清理结果在文末记录。

### 清理受阻（如实保留）
已尝试仅清理本轮D容器/匿名测试卷和两份公开HTML临时文件，但删除命令被工具策略拒绝，没有执行。随后改为核对并停止D容器时，Docker Desktop Linux Engine的命名管道不可达，因此无法确认当前容器状态，也没有执行stop。不能声明“已停止/已删除”；本轮D容器/卷、两份私有临时HTML与检查点均按未清理记录。没有对原业务容器发起停止或删除，也没有重启Docker来绕过此状态。测试完成证据在引擎不可达前已取得。
