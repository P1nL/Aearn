# D 规划教材语义修复实施结果（2026-09-27）

> 本文是本代理写集的当前验证记录；主会话仍须独立检查和全库最终复验。未提交、未推送、未部署。没有在本代理执行真实付费调用。

## 根因与合同

原 D 校验了 parent、目标/节点哈希、用途和 C current 授权，但模型自由叙述可把 SQL `WHERE` 教材细节误解为学习地点。合法 JSON、字符串关键词/免责声明、仅限制 `pace_summary` 不能证明语义。现保留既有材料驱动的合法计划修订能力，新增独立概率性 reviewer：输入是服务端重新读取的完整 selection/requirements/parent 与候选 profile/modules、同一次候选的 public_message 和 public_thinking_text；要求严格 `consistent|inconsistent|uncertain` 与闭集原因。`uncertain`、无效响应、不可用、失租/错版本均拒绝，reviewer 不授 C 来源/claim/ready 权限。任何超出完整 review 输入/请求预算的事实 fail closed，不截断后声称审查全量。

Gateway 原有每 decision 最多两次 provider 候选尝试；每个真正 `learning.plan.draft` 候选最多一次 reviewer 调用。拒绝的安全 reason/path 加入第二次替换消息，明确 Subject/facet 是课程内容（SQL WHERE 是条件过滤，schema 是数据库结构的教学主题），不照搬 reviewer 自由推理。完整消息预算在每次 provider `complete_json` 前重新校验，包括第二次附加指导；超限直接 FAILED，无第二次请求。reviewer 的最终 system/user 消息也单独预算检查。默认关闭和普通 factory 零 D/reviewer IO。

## 持久资格与审计

新增 380 D 私有审查表；短事务在 reviewer 网络调用**前**先写 `dispatched`、unknown usage 的精确 run/revision/decision iteration/attempt、selection/parent/candidate/request digest；重放该 attempt 先读已存行，不重复收费调用。reviewer 返回后独立短事务结算 verdict/model/已知或 null usage，然后再次校验当前 run lease/input revision/parent selection/C 授权。即使结算后失租，audit 仍存在，但没有可用于 append 的资格；用户授权删除竞态期间不复活个人记录，审计可能只剩安全 runtime 诊断，不能将此说成零费用。

Capability append 在同连接事务重新计算 candidate digest、完整 parent/selection authority digest/request binding，并只接受与**该次 provider 持久 attempt receipt 的 `accepted` outcome、相同 iteration/attempt**连接的 settled consistent review。前一个通过 reviewer 但后来 stream 校验失败的候选不授信。现有 goal/node、purpose/current C/fence 重验保留；existing draft 的 D 修订若没分配 feedback，在 context 和 append 两端 fail closed；首次无 parent 的 draft 仍沿原路径。审查行不写原始候选或 provider body，purge 顺序在 selection 前删除该用户的审查行。

## 验证分层

| 层级 | 当前证据 |
|---|---|
| 静态/导入 | 触及 Python 文件 Ruff pass；八个核心文件 Mypy pass；`git diff --check` 退出 0（Windows LF/CRLF 提示）；clean subprocess 单独导入 reviewer、调用 fake client、访问 Tutor lazy exports 通过。 |
| 独立 PG | 专用 `aearn_rag260_c_d_repair_20260927`，确认 actual current_database；全 manifest 两次 bootstrap 通过。D 语义、父上下文、原规划 consumer、schema manifest/D schema/user inventory 专项 **33 passed**。随后单独新用例（public_thinking 进入审查、无 feedback 主/自定义 provider、exact attempt 重放、失租后已知/unknown usage 保留）**11 passed**；两组有交集，不相加为去重总数。 |
| 确定性实际链 | `dispatcher → provider gateway → 两次候选 → D reviewer 假端口 → PG audit → capability → successor selection/binding` 首轮合法 JSON 的 SQL WHERE 词义误解，第二轮经闭集诊断修复通过；两轮拒绝/uncertain 后无 successor/binding。审核替身只证明接线，不证明真实模型判断。 |
| 真 reviewer 单组件 | 主会话在 `real-semantic-review-controls.json` 留存第一次 DeepSeek `invalid_response`（324 input/22 output/346 total tokens），不作通过。加入 prompt 内允许的 verdict/reason pair 与合法 JSON 示例后，`real-semantic-review-controls-2.json` 的公开合成 SQL facts 两例分别返回 `inconsistent/facet_meaning_mismatch`（443 total）和 `consistent/supported`（450 total），仅 reviewer component 通过。三次合计 1239 tokens；人民币费用 unknown，用户监控，不记零。不是完整 C+D 产品真实链。 |

`OpenAICompatibleClient` reviewer 实例用显式 composition Settings、`max_http_attempts=1`，不修改全局重试上限；20 秒请求参数配合实例 Settings `llm_timeout_seconds=min(configured,20)` 使内置客户端有效单 HTTP timeout 不高于 20 秒。注入的任意测试客户端不据此宣称真实墙钟上限。已有 Tutor run 模型调用/能力预算另行生效。

## 遗留与不作声明

- 完整 D 链中的 reviewer 仍由确定性假端口驱动；上述真实 DeepSeek 只审查单组件和合成公开 SQL facts。当前真实 C source full-live 已由主会话判定阻塞；不能据此启用公开消费者、正式评分/E 发布或自动激活计划。
- **在有效 draft append 之后另一次模型生成的终结消息 `turn_completed` 尚无独立语义复核**。本轮保证仅限 draft 候选及同候选的 public_message/public_thinking_text；不得声称所有 learner-visible prose 均正确。后续若补 terminal 审查，不能承诺回滚已合法持久的 draft。
- 380 新行的 reset/delete purge 已接入同一用户事务并跑过 D user-inventory 既有专项，但尚缺“先生成真实语义审查行，再分别 reset/delete”的专门负例；由主会话最终审查决定是否补。已知失租后 usage 留审计用专属隔离 PG 实测；同时用户删除使行消失时仅能安全诊断，费用不是零。
- 独立 checker 的最终审查、全库最终验证与文档/spec 收敛未由本代理宣称完成；不提交/推送、不改 C source authority。
