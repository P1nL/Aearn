# Tavily 获取切换结果

记录时间以伴随 JSON 的 UTC 时间为准；文件日期采用宿主 Asia/Shanghai 日期。用户明确要求改用 Tavily 抓取，并允许 Tavily 搜索测试。只扩展当前 D 任务，不创建新任务、不启用公开消费者。

## 已验证通过
- 免费配额预检：Tavily `/usage` 返回 Researcher、plan_usage=2/limit=1000、paygo_usage=0。未升级付费搜索。
- Search basic 探针 1 次：约 1.999 秒找到精确 SQLite SELECT URL；request `8d871b72-cfdb-4d78-bebb-c1c93a87b965`，reported credits=1。
- Extract advanced 探针 1 次：约 0.743 秒、43,729 UTF-8 bytes、failed_results=[]；request `78200125-7ac0-4d9b-b157-36a874613679`，reported credits=0。探针没有冒充正式已派发 capture。
- 新当前 policy/root 下先持久化 dispatch，再实际 Extract 1 次，成功保存同样的 Markdown。正式 request `415b2392-a668-4401-9df3-5df5bd2d84c5`，reported credits=0；正文 hash `398ef147b444ef7cc28c1138e31f3aefed088ae9411595d6023463aec606371e`。
- DB-only 独立服务用原生 Markdown profile 审核 WHERE/LIMIT 两段；partial corpus `dfcd678c-7eaf-44f1-b495-cc2d5a8577be` 已在专库激活 generation=2。旧 direct attempt 与 capture 历史未改写，没有第六次直接 GET。
- 真实模型产生后继草案 `33786733-3fbb-4e05-b440-fa17ee63c5d6`（v2），指向真实父稿 `8dca289e-495f-403d-91fe-833312a1ecff`。目标 hash 保留；1 个 `sql.queries/supplementary_explanation` binding；语义 review `fee718ce-3da2-49f3-98fc-3c83364a7a96` 为 consistent/supported。独立 DB 读取已重新校验 binding 当前授权。

## D 尚未完整通过
- 真实 target `8bdc8d8c-dca1-4f3f-b192-584313cb382d` 在已保存草案之后又尝试重复起草。末轮修复产生超过普通字符串上限的 profile/module 参数，被正式合同拒绝；terminal=`model_unavailable`、diagnostic=`TUTOR_PROVIDER_DECISION_INVALID_VALUE`。不能因为已经有 successor/binding 就把完整 D 标 passed。
- 本轮真实模型 HTTP 5 次（含语义审核及修复），prior=28、实际累计=33，本阶段 cap=6、累计 cap=34；全部保留 usage，不将未知人民币费用记零。停止新增付费重试。
- 四个前置未达模型的 target 也保留：旧 target deadline_exhausted；首次新 target 在分配冲突修复后反馈过长失败；第二新 target 同一反馈长度原因；第三新 target required-fact 槽位不足。它们均 0 HTTP，不复活旧 terminal run。
- 当前只补充查询片段 ready；schema、main_teaching、assessment 缺口仍在。未运行 E、Gate/公开 release，未 commit/push。

## 附带最小集成修复
1. Parent feedback 幂等键包含目标 run/revision；新 target 不抢用旧不可变 assignment。
2. 长反馈按完整 entry 分片，保持每块 1200 字符上限；内部 D required-fact slots 为 24，普通路径仍 8，正式 token profile 未变。
3. 安全 CLI 失败诊断只输出类型及文件/行/函数，不打印来源正文、密钥或任意异常内容。

## 定向验证
- HTTPX transport + 原生 reviewer：15 passed。
- 全新独立 PG `aearn_rag260_c_d_tavily_check_20260929` 的 provider capture 3 项及 manifest 5 项：8 passed。首次 fixture 将 Python list 误传 JSONB，已改为 JSON 序列化后通过；未触碰业务 5432。
- 新目标幂等/反馈分片：2 passed；没有扩展防御矩阵。
- 真实抓取、审核、准入、后继生成、精确绑定与当前授权逐层证据见 `tavily-switch-result-20260929.json`。完整正文和签名私钥仅在私有存储，不进入任务附件。
- 最终定向 Ruff、Mypy 5 个业务文件、`git diff --check` 均通过；GPT-5.6 Sol 交叉检查未发现 Tavily 正常链路阻塞或原始 HTML 伪标。CLI 成功层级另显式附带 representation 与 `origin_transport_attested=false`，不能单独把 real_sources 解读为独立 origin transport proof。
- 异常恢复边界：provider 已成功但 DB settlement 失败时须先查 durable attempt；capture 已提交但 summary 写入失败时以 DB 为准。不得换 UUID/操作键再次抓取。此次未发生这两类异常，不扩展恢复测试矩阵。
