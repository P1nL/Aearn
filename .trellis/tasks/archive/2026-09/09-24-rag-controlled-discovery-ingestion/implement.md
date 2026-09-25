# RAG B 实施与验证清单

## 前置与所有权
- [ ] 以当前 main、父计划和 A 已归档合同重核；读取 `.trellis/spec/backend/index.md` 指向的 database、grounding-material、corpus、retrieval、logging、安全与质量规范及 `docs/README.md`。记录工作树/并行所有者；不碰现有不相关改动。
- [ ] B1 先独立验收，B2 在其后接入；schema manifest、schema test、数据库 source of truth 由主代理/唯一 schema owner 串行持有。子代理只在不相交文件集改动；主代理审其方向、差异、测试和真实边界后整合。题库 P1/P3 的预算 root 与义务交接在 schema 冻结前核对。

## B1
- [ ] 实现可信需求解析、准入池先查、campaign/按需共用 job；敏感信息投影、policy 和四个开关 fail closed。
- [ ] B1 增量表及仓储：canonical root、周期/上限、预留/尝试/结算/未知、lease generation、候选/发现 receipt；跨 query/URL/job/profile 并发幂等。短事务，外呼不在事务内。
- [ ] SearchPort + 受控 Tavily 适配及错误分类；仅确认账户耗尽给 `existing_only`，无替代 provider。测试假客户端/异常矩阵，真实调用需独立许可和成本边界。
- [ ] B1 代码/PG 测试覆盖权限变更、额度、失租、重启/回放和共享/私有清理；独立 B1 review gate 后才进入 B2。

## B2
- [ ] 独立受限 fetcher 和网络出口协议：HTTPS、DNS 固定、peer/redirect、私网/metadata、压缩前后限额、类型、时限与取消；无 cookie/token/proxy 绕行。缺可证出口时 live 关闭。
- [ ] 有界 HTML/Markdown/plaintext 解析与代码/表格/列表结构测试；不改旧 parser 输出/fixture；精确 repo commit/path，不执行代码。
- [ ] B2 增量表、候选暂存/来源/留存与到期清理；数据分类、清理/导出隔离、不得向正式检索/规划/题库可见。schema owner 串行更新 manifest、文档和测试。
- [ ] 离线 SSRF/redirect/DNS/peer/炸弹/私密/权限撤销/同源镜像测试；真实 fetch 必须有已批准 egress 和公开测试来源，否则明确 `not_executed`。

## 综合验证和停止点
- [ ] 在用户指定/明确可丢弃的本地隔离 `aearn_rag260_*` PostgreSQL 库核对 `current_database()`，禁 dotenv 与 LLM，bootstrap 两次，运行 schema、B1/B2、corpus inventory/repository/retrieval 回归；未确认目标时不触碰 DB。测试只对本任务拥有的数据做清理。
- [ ] API 项目最小 pytest、Ruff、Mypy、`uv lock --check`、`git diff --check`；核对无新增公开 route/beat、四开关默认 off、无真实 provider/DB/egress 结果被离线测试冒充。
- [ ] 独立 `trellis-check` 后主代理逐项复验 PRD，记录执行/未执行证据。若配置或现场不具备，保留 B 未完成状态，不用 mock 宣称真实完成。完成后的 spec 更新、窄提交/归档按 Trellis Phase 3 单独执行，不推送远端。
