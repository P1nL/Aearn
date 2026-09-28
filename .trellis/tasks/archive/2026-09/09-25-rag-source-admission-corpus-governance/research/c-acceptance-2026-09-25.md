# C 阶段验收完成：真实自动审核、准入及隔离激活（2026-09-25）

## 当前结论

C 的获准隔离验收闭环已完成：真实capture → 独立自动审核服务 → 机器签名回执 → 用途准入 → candidate corpus → 动态验证 → CAS active。正常流程不要求真人签名；旧人工待审draft仅保留作历史/可选干预，不再阻塞。

**本次批准的是 WHERE 和 LIMIT 两个精确原文单元用于 supplementary_explanation，不是整页、主教材、评分证据或完整SQL课程资格。** 公共D/E消费者保持关闭。代码尚未commit/push，任务工作流待Phase3.4提交与归档；本文件结论是工程/隔离验收完成，不是生产发布。

## 真实数据库证据

| 项目 | 实际结果 |
| --- | --- |
| 隔离DB | aearn_rag260_c_live_20260925_01a0d3d4 |
| 完整capture | f36a8496-cb49-4b0c-a8db-f84c3fa1b528；2,033,807 bytes |
| 正文SHA256 | a6d38ca170dff62177e74e63297b44e567f673e7d2111de923e33b481560c140 |
| 自动review | bf3e6f86-4961-4aee-b202-afaf8c2ec03a；QUALIFIED，仅受审片段范围 |
| 审核服务身份 | service.sqlite-select.core.v1；automated service，非human |
| 机器回执SHA256 | 5c8576b621eeef001a9f28f10ac7ed8bca036c6ed5a8c582ac9f653f9a27b042 |
| 正式admission | 1；仅supplementary_explanation |
| corpus | 0ef889a8-0077-475c-82bc-e8fa16f0b705；published |
| active pointer | route.sql；generation=1 |
| 正式chunk | 2个，合计483 UTF-8 bytes，严格等于获审exact excerpts |
| 覆盖 | required=2、covered=1、gap=1、partial=true；缺schema |

首次命令返回 `partial_queries_activated_isolated_db`。相同run/corpus/回执再次执行返回 `already_completed_isolated_db`；active generation仍1，activated事件仅1，没有重复准入或重复激活。原unknown和后来settled抓取均保留，新增GET额度未被重置，本轮没有HTTP/provider请求。

用**公钥验证端（不读取签名私钥）**重新打开真实capture/current provenance和持久机器回执，动态复核review/admission、exact chunks与active摘要通过；DB quality_evidence_hash与canonical signed receipt hash一致。

实库负向检查：main_teaching→ADMISSION_STALE；assessment_evidence→PURPOSE_DENIED；full_required→COVERAGE_GAP。未为了完成C扩展用途或覆盖。

## 自动审核与隔离方式

- sqlite_select_automated_review.py使用有限精确profile，要求完整WHERE三句段落与LIMIT句子；在真实SQLite内存引擎运行固定WHERE真/假/NULL、LIMIT界限及组合检查，不执行网页中的SQL或指令。
- 接受正常HTML的可选结束标签，仍不从警告/否定/引用等上下文抽取貌似正确的子串。未知或不满足profile的材料自动拒绝，不转为强制人工待办。
- 回执绑定完整capture/hash/provenance、profile/service、SQL执行摘要、两个byte span/hash、用途和UTC期限；验证端重新核对，不能仅信签名或关键词。受审结论限profile片段，不认证整页或SQLite最新版本。
- SourceReviewRepository在准入和当前读取时限制用途；CorpusGovernance在创建/验证/激活/回滚时要求exact获审片段。已有可信完整审核适配器兼容，但不能被半实现的optional hooks降级绕过。
- 自动runner保持显式部署批准及root私有配置/密钥，receipt文件immutable/provisional不冒充DB提交。匹配provisional可复用，已完成run只读返回；无网络重抓。

审核镜像：`sha256:442da66e41c22299c7e338d980414a46dc5de9b6da0ed183ddf6d4d01d1349e0`。构建仅白名单源码、本地固定base、--network none/--pull=false；执行前比对审核模块/仓储/governance/runner的源码hash与镜像一致。审核容器仅可出站连接专用PG5432，处理进程root身份但CapEff/CapBnd=0、NoNewPrivs=1，无抓取网络或外部模型调用。真实捕获worker的旧镜像pin仍用于历史provenance，不与新审核镜像混同。

## 代码与测试

- B→C路径已具备独立per-capture正式用途/历史grant、当前B1授权身份/B2访问政策/完整capture校验、撤权否决及既有corpus唯一写者集成。
- 自动审核/excerpt gate的最终专用PG C套件：**211 passed、1 skipped**（Windows不能替代Linux SO_PEERCRED）；全manifest在该fixtureDB重复bootstrap两遍。
- 自动runner：**6 offline tests passed**；独立审核聚焦测试29passed/4PGskip；Ruff、Mypy、lock/diff检查通过。先前完整grounding/schema检查696passed/83skip属未配置DB运行，未冒充全部PG实测。
- 本轮纠正了负向fixture残留导致URL唯一冲突、当前review/admission读取的撤权并发窗口；没有放宽生产唯一性/撤权约束。

## 验收边界与后续

PRD七项验收按最新批准的自动服务审核与明确追加请求预算修订勾选。真实样本闭环已完成，评分用途/完整SQL不足按合同正确拒绝，B/provider实测和生产发布不在本轮真实执行范围。

当前机器回执及来源暂存许可截止 **2026-09-26 21:26:59（北京时间）**。活跃快照状态已持久化；未来当前用途核验仍须有效授权/回执，不能把本次时点验收当永久可用性。正式获审片段有独立历史保留许可。临时审核容器和PG已停止，私钥/回执保留于operator私有volume，不进入Git。

可以继续D的实现与规划集成，但不得把这个partial supplementary corpus当作完整基础SQL教材或评分来源；公开消费者仍须D/E自己的启用与验收。
