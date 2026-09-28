# C 验证证据（2026-09-25，进行中）

## 已执行

- 只在名为 `aearn_rag260_c_20260925_01a0d3d4` 的可丢弃 PostgreSQL 数据库运行 schema bootstrap 两遍；测试先核验 `current_database()`，各 PG 用例回滚。C schema/来源仓储/审核仓储/动态 corpus 的合成测试已经跑过；合成正文 `SELECT ...` **不是** SQLite 实际页面。
- 最终定向复跑 `tests/grounding tests/database/test_schema_manifest.py tests/database/test_rag_c_schema.py` 在隔离 C 库 **566 passed、66 skipped**；新增独立回归 4 passed（包含在 566 中）。Ruff、Mypy app、`uv lock --check --offline`、`git diff --check` 和 Trellis context validate 通过。
- `rag-c-source-control` Unix socket 签名/nonce/一次完成协议只有离线测试；WSL/Linux 离线也不是现场容器隔离证明。

## 未执行/阻断

- C 目标页真实隔离 GET = **0 次**，Tavily/provider = **0 次**；没有真实页面捕获、审核、入池或 active。可丢弃库的合成 CAS/部分 coverage 不等于真实页面/生产发布。
- host-only PG callback、实际 peer socket 参数与 signed pre-dial/worker report 已接线并通过 synthetic Linux/PG 测试；独立旧 `RegisteredSourceRepository.settle_capture` 仍 `LIVE_BRIDGE_REQUIRED`，真实结算只走新桥。尚未执行最终双容器的分阶段 signer pin 交接、真实 worker composition 和完整防火墙验收。
- 已实现默认关闭的 operator Ed25519 签名质量审核器及当前 PG provenance resolver；尚无真实 reviewer 公钥授权、精确实际正文审核签名或真实 capture。不能把 synthetic key/测试 fake 或 DB 的 `QUALIFIED` 字符串当作真实质量审查。
- 已新增 C 注册捕获正文到期/撤权物理清理（调用方事务、operator 开关）、双重历史授权与 schema link guard，隔离 C 库 9 项关联 PG 测试通过。但没有自动 scheduler、备份/WAL 保留审计，正式 corpus 仅凭独立永久历史 grant 保留不可变文本；若该 grant 不成立则阻断入池，不能将审核读取拒绝冒充物理擦除。
- 当前 C 动态 corpus 仅支持注册源；B full capture 进正式 corpus 需另接当前 B 权威。未启 D/E consumer、未碰真实用户库或生产 active。

## 下一现场 gate

双容器方案已获用户批准，无需重复索取同一方案授权。下一步是最终镜像与临时 key 的独立 pin 交接、operator 控制的真实 worker 接线及完整 namespace/firewall 验收；通过后才可消耗唯一 GET。质量准入还须真实 capture 上的外部可信审核输入。任何缺项维持 not_executed/blocked，不降级主机请求、不重试。

## 2026-09-25 续跑补证（非真实来源）

- 已核对并运行跨 policy/generation 的 URL 唯一回归测试；当前 schema + host Windows 定向 27 passed、1 skipped。
- 用本地固定摘要 Linux Docker 镜像、非 root UID/GID 65534:23456、只读源码及纯 Python 测试依赖挂载，显式连接同一可丢弃 C 库，host callback 独立测试 26 passed、无 skip。包含真实 Unix socket peer + PostgreSQL 结算/重放/回滚，以及 transport_proof/hash/key pin/image pin 落库断言；正文和签名均为合成 fixture，不是页面捕获，不证明完整桥/真实出口。
- 修复 C 离线 Compose bootstrap capability 缺口：真实 --network none 容器证实无 CHOWN 时 os.chown EPERM，加入 CHOWN 后成功；SETUID/SETGID/SETPCAP 仅用于 bootstrap，setpriv 后 worker CapEff=0、CapBnd=0、NoNewPrivs=1。不是实际防火墙现场验收。
- 6 Sol 独立 read-only check 已成功完成，没有确认剩余 P0/P1 绕过；报告明确 live composition/真实审核仍未验收。后续新增的 proof 持久化和 operator 签名审核接口仍需最终集成复核。
- 不再丢弃已验证的 transport proof：host 结算存 canonical 有界证据、SHA-256、独立配置的 signer key pin 与 worker image pin，legacy/synthetic nullable 行不能直接作为生产审查来源。
- 新增默认关闭的可信 operator 签名质量审核器；无外部 reviewer 公钥/精确正文审核签名/当前 provenance resolver 时仍拒绝。44 个定向 synthetic-key 测试通过。没有创建生产 reviewer 密钥或签名，也未把模型判断当成人工审核。
- 真实 SQLite GET 仍为 0；没有 commit/push/生产 active。

### 本轮最终复跑

- 显式 `DATABASE_URL` 与 `AEARN_RAG_C_TEST_DATABASE_URL` 均指向已核对的可丢弃 C 库、`LLM_TYPE=disabled`：`tests/grounding tests/database/test_schema_manifest.py tests/database/test_rag_c_schema.py` 为 **694 passed、53 skipped**。所有合成 fixture 回滚。
- 新 PG provenance resolver 的两项集成测试已由主会话在上述专库实际执行，包括用 synthetic reviewer key 验证「持久 transport proof → 当前 PG provenance → operator 签名质量判断」，撤权后拒绝。不是生产 reviewer 或真实来源审核。
- Ruff 和 `mypy app`（316 个源文件）通过，`git diff --check` 通过；C Unix bridge Linux unit 11 passed，C offline preflight unit 11 passed。基础依赖锁离线检查通过。
- 批量 retention 测试原来对同一 URL 造两个 capture，与新的一页一次约束冲突；改为不同 `example.org/retention/<fixture-id>` 合成 URL，不放宽真实 URL 一次性约束。
- 新的 `.trellis/spec/backend/grounding-source-admission.md` 记录具体签名、proof 与 worker 报告的区别、跨 PID namespace peer=0、bootstrap capability 最小需求和验证边界；已加入 task context。
