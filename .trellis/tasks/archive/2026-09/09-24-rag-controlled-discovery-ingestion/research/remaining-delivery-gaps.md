# Research: 完整 B 包最小剩余项
- Query: 当前实现对照子 PRD/design/implement 与父 B1/B2 接受边界；区分默认 off 编码和单独现场授权。
- Scope: internal
- Date: 2026-09-24

## Findings
- 主代理报告 grounding+schema **404 passed / 29 skipped**；本研究未复跑，也未核验 skip 原因。它证明所运行离线/允许环境用例，不是 PG、Tavily、egress 或 live fetch 的总括通过。
- 边界：子 `prd.md:3-4,18-24`、`design.md:3-13`、`implement.md:7-22`；父 `phase-ii-implement.md:31-49`、`phase-ii-design.md:12-21,44-54`。B1+B2 均完成才称完整 B；C 准入/激活和 D/E 消费不在 B 内。

### B1：可编码、保持默认 off
- [ ] 生产可信 context：实现 `DiscoveryContextResolver.resolve_issued/resolve_job`、`AuthorityResolver`、`QueryProjectionResolver`，持久发行完整 demand、actor、scope/version、purpose、policy generation、delegation，重取 job 时重核而非信模型/hash。接 `DiscoveryBroker`→`PostgresDiscoveryWork`；见 `autonomous/discovery_work.py:27-50,66-125,127-156`、`access_policy.py:52-58,113-149`。
- [ ] 生产 `QualifiedCorpusPort.assess` 精确核已准入材料的版本、用途、覆盖/适读性；基础 campaign 与按需缺口共享 broker/job/root；命中不搜索。见 `discovery_broker.py:40-68,236-265`、`hybrid_retrieval.py`，不读 staging、不增公开 route/global beat。
- [ ] 服务端 root/period/cap/delegation 的配置与失效接线，和题库预算义务同 canonical root；`PostgresBudgetPolicyResolver` 只读已启用 root，bootstrap 默认 disabled。见 `budget.py:29-70,146-218`、`270_rag_discovery_jobs.sql:4-25`；启用余额/成本另批。
- [ ] 生产 `UsageAuthority.verify_usage/verify_account_exhausted` 和未知用量对账：provider 返回/本地 hash 不能自证账单；只确证耗尽可 `existing_only`，超时/401/普通429 均保留未知或失败。见 `discovery_work.py:42-50,251-318`、`tavily_search.py:173-181,205-220`、`discovery_broker.py:388-408`。
- [ ] 默认 off 的受限 worker/queue：领 job、持久 dispatch CAS、lease fencing、重启/重放和失败恢复；启动/外呼前校验四开关与独立网络费用许可。现有 `jobs.py:1,30-38` 无入口，`aearn/services/worker/` 无 B 消费接线；`app/core/config.py:82-85` 四开关默认 false。

### B2：可编码、保持 live off 直至独立批准
- [ ] 生产 discovery/probe 与 `StorageGrantResolver`/撤权 authority，逐 candidate 核域/path、root、receipt、lease、none/prefix/full、期限；`retention.py:22-85`、`intake_service.py:37-55,57-157,177-240`、`staging.py:40-115,202-229`。具体可探查范围、内容许可和保留期需用户/部署方单独批准。
- [ ] 独立 live readiness/egress 实现，不能仅把 `offline_protocol_test` 改 true；none/prefix 必须有界读取，不先完整下载。当前 `intake_service.py:264-274`、`safe_fetch.py:204-212`、`staging.py:40-43` 明确挡 live；复用 `public_dns.py`、`pinned_tls_connector.py`、`safe_fetch.py:242-304` 的逐跳 DNS→固定公网 IP/peer/TLS、重定向及字节/类型/取消约束。
- [ ] 默认 off 的实际 intake/过期与撤权清理队列，授权前后短事务复核；`provenance.py:44-121`、`staging.py:113-229`、`280_rag_candidate_staging.sql:1-51`。请求链/最终 URL、capture 范围及对应 hash、许可/作者/精确 repo revision、镜像家族分别留证；搜索摘要不能当正文，暂存不能供 corpus/retrieval/plan/item 使用。临时/失败/日志/缓存/队列副本同样受留存约束。

### 私有引用与证据分类
- [ ] 可信 actor↔user 映射后接 `local_user_data_repository.export_user_data/reset_user_data/delete_user_data` 与 `routes/users.py:69-137`：仅本人非敏感 job/candidate 摘要可导出；reset/delete 同事务 unlink `rag_discovery_job_refs`、`rag_candidate_private_refs`，共享账本/receipt/capture 保留。`jobs.py:17-20,178-198` 有授权 unlink，`staging.py:194-200` 依赖调用方核 owner；双用户反例并更新 `test_rag_b_inventory.py:24-29` 的未接线断言。
- [ ] 隔离 PG **另证**：用户先指定/确认可丢弃 `aearn_rag260_*`，核 `current_database()`，bootstrap 两次、跨连接并发/回放/失租/未知、双用户清理与旧 corpus 回归；`test_rag_b_inventory.py:32-50` 无 URL 即 skip。29 skipped 需主代理分类，不可据总数判断 PG 已做。
- [ ] 真实 Tavily **另批网络/credential/费用上限**，记真实 usage 与耗尽凭据；隔离出口 **另批部署**，独立证明 IPv4/IPv6 loopback、私网、link-local、metadata、重定向不可达；真实 HTTPS fetch **另批来源/path/网络/存储许可**，记 TLS/peer/跳链/最终 URL/内容 hash。分别 `not_executed`，mock 不代替 live；未经批准仍保持 live off。
- [ ] 主代理记录 404 passed/29 skipped 的具体命令、skip 分类和 Ruff/Mypy/lock/diff 结果；不把源码/MockTransport/隔离 PG 的不同证据混称完整 B 现场验收。

### Files / specs / external references
- 关键实现：`autonomous/{discovery_broker,discovery_work,budget,jobs,tavily_search,intake_service,safe_fetch,retention,staging,provenance}.py`；schema `270_rag_discovery_jobs.sql`、`280_rag_candidate_staging.sql`；用户接口 `local_user_data_repository.py`、`routes/users.py`。
- 相关规范：`.trellis/spec/backend/{index,grounding-material-contracts,grounding-corpus-operations,database-guidelines}.md`；`docs/architecture/database-schema.md`。外部参考：无；未访问网络/provider/DB/密钥。

## Caveats / Not Found
- 未发现生产完整 context/usage/root/worker 接线、独立部署 egress 证明或私有引用接入现行 export/reset/delete；已有 PG 表与离线协议不是 live 证据。并行工作树可能变化，主代理整合时复核；本研究未运行测试或执行 Git 操作。
