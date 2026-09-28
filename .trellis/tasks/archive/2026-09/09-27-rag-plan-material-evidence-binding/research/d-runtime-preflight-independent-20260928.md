# D runtime cutover preflight 独立复核（2026-09-28）

## 结论：源码 GO；live 执行仍须主会话门禁

仅 `aearn/infra/rag-d-live/runtime_preflight.py` 的**独立、显式 operator preflight** 可进入主会话的下一道部署/执行核验。它不是 C 来源准入、real parent 模型调用、D successor、公开 RAG 或全链通过证明。本轮未触及已经冻结/运行中的 source 文件，未连接 live DB、未发来源或 provider HTTP、未读取 provider secret。源码审查没有发现需要窄修的确定性缺陷，故无代码改动。

## 实际控制流与范围

- CLI 缺 `--execute` 时 `guard_request` 在文件/DB 访问前拒绝；要求 root POSIX 操作者、单独声明的 `aearn_rag260_c_d_*` 精确库名及有界 operation ID。只从 root-owned C control config 读取 private DSN；`approved`、config.database_name、解析出的 DSN dbname 与声明名必须相同。建立连接后再次读 `current_database()`，不从 ambient `DATABASE_URL` 选择目标。**仅库名一致不足以证明真实部署身份**，PG private network/镜像与配置挂载必须由主会话另核。
- `execute_on_connection` 要求 caller-owned 非 autocommit 事务；锁超时5秒/语句超时15秒，在 owner advisory lock 后以 `tutor_runs SHARE` 防止 legacy run DML 穿过 dry_run→prepare。`_clean_inventory` 要求 schema/worker/history 前置项就绪且 legacy_nonterminal、active_legacy_leases、ambiguous_effects 全为0；失败回滚。实际状态转换仅调用 `TutorThreadTurnCutoverService.prepare`、`enable`，使用返回的 generation/summary_hash，之后用 owner `status`/`assert_mutation_allowed` 和同 generation 的 preparing/preflight/enabled 审计事件核验；已 enabled 只复核、不重启。没有直接 SQL 填 cutover 状态、没有自动 rollback/re-enable，也不会迁移非终结历史。
- 显式 `Settings` 关闭 LLM、Codex runtime、B 发现/C 采集/自动激活及 RAG evidence consumer；文件没有 provider config、模型传输或公网取源调用，stdout 仅固定状态/版本/摘要/审计事件种类，异常仅安全代码。私有 C DSN 是此命令唯一必须读取的 secret，不打印。这里的 `effective_enabled=True` 是**为本 operator preflight 显式传入的 thread-turn v2 环境 gate**，不是公网 RAG 已发布，也不是未来独立进程真实环境已开启的证明。
- `real_parent.py`、`prepare.py`、`run.py` 不导入或隐式调用 `runtime_preflight.py`；真实 parent 后续仍通过公共 `/api/harness/cutover` verified 和 `/api/tutor/capabilities/thread-turn-v2` effective_enabled，不能用 preflight 回执跳过 learner Harness cutover。未修改真实 parent 流程或模型 harness。

## 独立验证

- 全新隔离 fixture 库 `aearn_rag260_c_d_gatefixture_independent_20260928_01`，WSL PG `127.0.0.1:55438` / `aearn_d`，先核 `current_database()`；完整 schema manifest 41 fragments 连续 bootstrap 两次。仅此测试库写入。
- 显式 `AEARN_RAG_D_GATE_FIXTURE_DSN`：`tests/test_runtime_preflight.py` **17 passed，0 skipped**（其中3项直接 PostgreSQL）；整个 `aearn/infra/rag-d-live/tests` **50 passed，0 skipped**，两次计数相互重叠。
- Ruff 对 `runtime_preflight.py` 与对应测试 **pass**；Mypy app `--no-incremental` **326 source files pass**。没有改 source/模型 harness 文件。

## 主会话 live 前仍需确认

1. C 当前有效 reviewed/admitted supplementary 材料与相同 exact 隔离 DB 已落盘且未过期；本脚本故意报告 `source_admission_checked=False`，不代替这道门禁。不得把上述 fixture 库或旧 synthetic parent 当真实来源。
2. 使用当前审核过的 D-only 镜像、私有 PG 网络、root-owned C control config/DSN 只读挂载；无 provider 文件/credential、无一般出口和 C worker namespace。再次验证 `config.database_name`、DSN 与服务器 `current_database()` 三者同一目标，且 legacy inventory 为零。
3. preflight 成功提交后，独立 real-parent 进程仍需真实公共 capability 与 learner Harness cutover、provider 配置/请求预算/真实 provenance 验证。此源码 GO 不授权本代理或操作者自行启动模型，也不启用公开 RAG consumer、题库或 E。
