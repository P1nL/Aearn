# B 包中途验证记录（未完成，不是验收结论）

- 工作分支 `codex/rag-controlled-discovery-ingestion`；任务 `in_progress`。本轮独占可丢弃本地 PostgreSQL 库 `aearn_rag260_b_20260924_01a0d3d4`，经 `current_database()` 核对；没有接触原学习库。
- 当前 manifest 顺序 260→270→280；在该库 bootstrap 两次成功，B1/B2 PG 和旧 corpus repository/inventory 回归先后通过。B1 dispatch CAS/账本 PG 测试通过；新 staging 清理 trigger 已再次 bootstrap 并验证。
- `pytest tests/grounding tests/database/test_schema_manifest.py -q`：404 passed、29 skipped（显式隔离 URL、其他 provider/旧情景条件不足的跳过按各测试理由核对；不统称全部验收通过）。
- `ruff check app tests`、`mypy app`（296 files）、`uv lock --check --offline`、`git diff --check`：通过。Git 发出已跟踪文件 CRLF 转换提示但无 diff check 错误。
- 本轮未运行 Tavily live Search、真实 HTTPS fetch、部署出口隔离、真实留存政策/用户 reset-export 全流程、生产 worker/campaign 触发；离线假客户端/假 DNS/假 TLS 不可代替上述现场。
- 子代理审查后修正了 B1 dispatch 只能持久一次、已结算零候选作业收尾、B2 none/prefix 不能全量读取后丢弃、DB clock 租约复核以及暂存清理原文+片段联动。修订后的 scope 测试见上述结果。
- 尚未进入 Phase 3，不得据此宣称完整 B 包或 push/归档。

后续增量：manifest 增加 290 私有 context、300 operator 候选政策、310 服务 campaign；同一专用库复核 `current_database()` 并再次 bootstrap 两次。B1/B2/CandidatePolicy/Context/Campaign 及 user export-reset-delete 双用户隔离 PG 用例已跑。最终本轮定向命令 `uv --directory .\aearn\services\api run pytest tests/grounding tests/database/test_schema_manifest.py ..\worker\tests\test_rag_b_worker_routes.py -q` 得 494 passed、29 skipped；Ruff/Mypy（303 个源文件）/离线 lock/diff 通过。未跑真实 Tavily、受限出口/live fetch，现有默认关闭及 worker composition 缺口保持未完成。此前 404 仅是中途快照，不作最终结论。

后续执行：隔离库 `aearn_rag260_b_20260924_01a0d3d4` 经 `current_database()` 确认，新增 schema 仍按完整 manifest 再应用两次；纠正 staging PG 测试对持久 root authority 的夹具缺口（不放宽仓储授权），并把旧 live 关闭错误码断言更新为现行 `LIVE_EGRESS_UNVERIFIED`。使用显式 `AEARN_RAG_B_TEST_DATABASE_URL` 与 worker 测试 URL，定向 B/manifest/worker：499 passed、43 skipped。43 个跳过均是旧 corpus CLI/service/retrieval 对独占库名的条件，不是 B PG 跳过；额外用两个新建且 `current_database()` 核对的可丢弃库 `aearn_rag260_cli_b_01a0d3d4`、`aearn_rag260_cli_retrieval_b_01a0d3d4` 各 bootstrap 两次，corpus CLI/service 23 passed、retrieval 7 passed；旧 repository 在 B 隔离库 14 passed。Ruff、Mypy（305 files）、离线 lock、diff check 通过。尚有 B2 bounded none/prefix、生产 composition/部署工件的并行复核进行中，故这仍非最终验收。

集成复核发现：B1 `DiscoveryJobRepository.complete()` 将作业从 leased 改为 completed 并清空租约；B2 `PostgresIntakeReadiness` 与 `CandidateStagingRepository.stage()` 又要求同一 job 的 `require_live_lease()`，所以已结算候选即使有授权也无法实际摄入。不能凭队列 candidate UUID/旧租约绕过，正补一个仅对已结算候选、现行 root/权限有效的持久再认领与 release seam；在该链路被 PG 验证前，`intake` worker 继续关闭，B 包不能宣称完成。

最终代码检查快照（提交前，仍默认关闭）：完成候选专属持久 intake lease（B1 结算后不得重用 discovery lease）、事故后只对既存 capture 作无重抓 reconcile、HEAD/精确 206/full 分别捕获与哈希、campaign `intake_approved` 默认 false、B2 worker 显式 operator config 与独立 retention 审批。`trellis-check` 发现并修正了 live capture 许可未带入暂存、candidate 锁下嵌套 DB 连接导致撤权排队风险，以及 intake 关闭误挡保留清理 3 项 P1；主代理复验改动。

当前本地执行：独占 B 库 `aearn_rag260_b_20260924_01a0d3d4` 核对 `current_database()`、最终 schema bootstrap 两次；B/manifest/worker 定向 **535 passed, 43 skipped**。43 跳过属于旧 corpus CLI/service/retrieval 的专用库名前缀条件，另在核对后的两库 `aearn_rag260_cli_b_01a0d3d4` 与 `aearn_rag260_cli_retrieval_b_01a0d3d4` 各对最终 schema bootstrap 两次并分别 **23 passed / 7 passed**；旧 corpus repository 在 B 库 **14 passed**。infra signed-egress 离线 unittest **8 passed**，Ruff check/format pass。API Ruff、Mypy app（306 source files）、离线 `uv lock --check`、`git diff --check` 均通过。未把模拟计入真实出口结果。

真实但有界的 **一次 Tavily + 一次公开文档 GET** 已在 `research/live-egress-preflight.md` 独立记录；它仅是同一临时隔离 namespace 的 transport smoke，不是生产 operator config、部署出口或存储许可证明。正文未落盘。`_load_operator_config()` 仍返回 None；生产成本、网络、保留政策和正式 C 来源准入要分别经过审批/上线验收，不能仅凭本地代码/演示打开。没有第二搜索商、公开 route、全局 B beat、自动正式准入或远端 push。
