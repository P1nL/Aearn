# D 修复追加验收：新鲜 C 来源侧车结果（2026-09-27）

## 结论

**真实 C capture→可信自动审核→准入→partial corpus 未完成；D 同一真实链 blocked。** 严格门禁已建立且单次已授权 worker 实际运行，但在 `stage=fetch / DEADLINE_EXCEEDED` 终止。不能把原 2026-09-25 的到期 C 回执、此处新登记 policy、无 GET 签名探针或合成 D fixture 当作现时来源。下文记录首次尝试；后续仅执行了一次经主会话批准的30秒补充worker调用，但在DNS/HTTP之前被策略拒绝，没有第二次SELECT GET。补充配置沿用了同一policy/generation，与现行成功合同不兼容；不是已经证实的schema350缺陷。首次unknown及未消费的不可变补充授权均保留，未尝试第三次调用或开启公开消费者/生产发布。

## 可核查事实与交接

| 项目 | 结果 |
|---|---|
| 新隔离 DB | `aearn_rag260_c_d_live_repair_01a0e0c7`；仅任务卷 `aearn-d-live-repair-01a0e0c7-data`，PG 容器 `aearn-d-live-repair-01a0e0c7-pg`，内部网络 `aearn-d-live-repair-01a0e0c7-internal`，无 published port。 |
| DSN 秘密路径 | 新 `aearn-d-live-repair-01a0e0c7-operator` 卷中的 `/run/operator/dsn`（C 控制容器挂为 `/etc/rag-c-control/dsn`）；仅提供路径，不输出值。D 测试容器须在同一内部网络只读挂载该卷，并再次校验 `current_database()`；不得将 DSN 放日志/Git。 |
| 新 source scope | `policy.c.dlive.repair.01a0e0c7` / generation 1 / `root.c.dlive.repair.01a0e0c7` / dispatch `0ffc109e-136b-4b99-b270-2896f8d92edd`；`route.sql`、`sqlite-docs-v1`、`queries`、精确 SQLite SELECT URL、`supplementary_explanation`，到期 2026-09-28 11:54:38 UTC。 |
| 授权结果 | 新 root/policy 在 arm 前当前有效，但唯一尝试现为 `unknown / DEADLINE_EXCEEDED`，response bytes/hash NULL；URL 唯一约束和流程不允许重新派发。仅官方页面 public-domain 许可事实，无新鲜质量授权。 |
| capture / review / admission / corpus | 全部 0；`capture_id=null`、`corpus_id=null`、active pointer 不存在。没有 `PostgresCurrentCaptureProvenanceResolver` 可验证的行，也没有当前 `SQLiteSelectAutomatedReviewVerifier` 回执/获审摘录可交 D。 |
| 公有 pins | C bridge `2a6be5d5e9192719237019bb97089c11a1a24a671b7deb1a88929c46f34ed7f3`；B signer `49616fdf987199fadf8710af0a8ae2998abf7e09830cd67889a2596e6ce67fb8`；服务审核公钥 `c3f7b56d5ccf7fa765ca6fabc50c9f519b18d8e5b0f032673cb1474906109e68`。临时 B/C pin 仅对应仍运行的本轮容器，不是抓取完成的证明。 |
| 任务文件 | `.runtime/rag-d-live-repair-01a0e0c7/` 保存非秘密脚本、root/policy/scope/public pin/request hash、预检辅助；`fresh-c-preflight.md` 保存详细门禁及失败时序。审核私钥原位，只通过历史 operator 卷的 `automated-review` 子目录在固定服务镜像中只读预检，不复制/输出。 |

## 运行与验证分层

1. `SELECT current_database()` C/D 均为新库；当时 39-fragment manifest 完整重复 bootstrap；查询旧/新 C 计数在 arm 前为 0。主会话 D 运行前仍须按并行演进后的**最终现行 manifest**再 bootstrap 两次。
2. 实际两网络+非 root 无 capability/no-new-privs、防私网/metadata/PG、IPv4/IPv6 kernel OUTPUT DROP 11 项负向计数、目标 443 纯 TCP 正向、C peer、B 真实签名无 GET 挑战、worker 静态 pin、固定自动审核镜像读取未改动服务私钥/公钥的 pin 校验均通过。首两次不完整配置在**arm 前**停换，具体见预检记录；不将探针冒充 HTTP transport proof。
3. **一次** root-only arm 和**一次** `worker_once.py --once`，受 10 秒 SafeFetcher deadline 与外层 45 秒 watchdog 限制；实际输出 `WORKER_ONE_SHOT_DENIED stage=fetch code=DEADLINE_EXCEEDED`，exit 1。目标 TCP ACCEPT counter 含预检和该次运行，不能判定 HTTP GET 是否实际发出/完成、TLS/响应/正文阶段，也无可信 body hash。没有 `curl`/替代抓取/搜索/重试。
4. 后验 PG：一条 dispatched attempt，无 response/capture；调用正式 `PostgresRegisteredSourceRepository.mark_unknown`，状态成为终态 `unknown / DEADLINE_EXCEEDED`，之后只读确认 capture/review/admission/active 皆 0。短效 arm 从本任务卷移除，历史审计行保留。C 自动 admission 因缺 settled capture **未执行**；D 真实来源消费者/绑定因缺现时来源 **不能执行**。
5. 本代理 Tavily 搜索 0、真实模型 provider 0、自动审核执行 0；没有费用人民币核算，不能说项目已消费 0 元。无提交/推送、无生产/公开消费者写入。

## 未解决与停止点

- 首要阻断：真实 worker 在 fetch deadline 中止；该次尝试的 HTTP 是否已发出不确定，**不能再用同一 URL/policy/dispatch 重试，也不建立另一个来源 policy/root/DB 绕开一次性边界**。只可由主会话另行审阅一次新的独立授权与无 GET 诊断方案；本代理到此停止来源网络动作。
- 原许可 fact 与当前 root/policy 不产生 `MaterialSelectionResult.ready`。`main_teaching`、`assessment_evidence`、完整 SQL (`schema`) 均继续为 gap/denied；没有任何可交给 D real harness 的 current source authorization adapter 输入。真实 provider 即使另行完成调用，也不能与此失败 C attempt 合并称作 C+D 真实全链路通过。
- 保留本任务 PG/control/egress 容器及卷运行供主会话读取；请勿清理旧/新 DB 基础设施，直到主会话完成证据消费。状态和公有输入在上述 `.runtime` 文件；秘密和私钥绝不放研究文档。
