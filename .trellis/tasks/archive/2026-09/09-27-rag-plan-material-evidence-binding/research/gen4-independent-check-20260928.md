# Gen4 独立核查（2026-09-28）

## 部署签名拓扑：部署 GO（仅离线预检代码）

- 真实 B `install`/`Attestor.handle`、Docker `--network none` + OUTPUT DROP、随机一次性 test key/容器/卷和固定本机 r2 digest；同镜像客户端以 65534:65534、supplementary 23456、cap-drop ALL、NoNewPrivs、只读运行。实测 separate-PID 拒绝、shared-net+PID 新 nonce 签名与固定测试公钥通过、wrong-key 在客户端拒绝。命令 `python aearn/infra/rag-c-live/signature_topology_preflight.py host` 本轮通过。
- 审查未发现放松 B peer 检查或 TTL=4 的修改；此 GO 仅认可离线脚本及后续当前 signer 的**条件性** pre-source 门禁，非当前 live signer/新镜像/源/DB 的 GO。任何实际 ARM 前仍须新独立 pin、当前 signer 负/正 probe 与 Docker inspect；不使用旧 gen3 回执、key 或授权。
- 自修：README live probe 原只 `--group-add 23456`，当 B/C GID 不同，`worker_once._identity` 会拒绝，且与真正 worker 的 exact supplementary groups 不同。改为分别由当前配置核定 B/C GID 并生成两个（去重）`--group-add`；将 live probe 的可优化掉的 `assert` 改显式拒绝，离线断言脚本在 `python -O` 下直接拒绝运行。均无新增 source 或 grant 权限。

## Gen4 授权代码：410 + 部署 GO（代码/离线门禁；不含 live GO）

- 独立检查 schema 410 对既有 400 表的增量变化：仅移除原 original 唯一约束并添加 `(original_attempt_id,generation)` 唯一键，generation 仅 3/4；历史行不改。gen4 allowance 检查 original/gen2/gen3 同 URL 三次 terminal `unknown`，第三次须追溯既有同 original 的 gen3 allowance，当前新 policy/root、source/Subject/version/facets/host/path/用途与字节上限核验，精确新 UUID/request/URL/expiry 与 approval ref；issuer 同事务插入 allowance + authorization。插入、授权和 dispatch 的旧 400 trigger 复用 410 覆盖后的检查；original `FOR UPDATE` 串行，计数要求恰好 3 次，发出第四次后不能再发新信用或第五次；无自动重试/来源 I/O。旧三次 attempt、auth、allowance 保留。
- 自加 gen4 并发签发 + 并发 dispatch 实 PG 回归，两个竞赛分别仅一次成功。合成库 `aearn_rag260_c_410_01a0e6b8`，核对 `current_database()` 的原 fixture；运行 gen4、gen3、repository、schema manifest **34 passed**。离线 Docker 签名拓扑 `OFFLINE_SIGNER_GATE_PASS`，runtime unittest **40 passed**；相关 Ruff pass、Mypy pass（3 Python 源文件），`git diff --check` 无错误（仅其他文件 CRLF 提示）。
- **合并 GO 边界**：410 additive 授权代码和离线部署脚本可供主会话下一步独立只读 live inventory、镜像/签名 pin 与当前 signer 负/正 probe 的条件门禁；本检查**不授予** live DB migration/新授权、ARM、实际 GET、C source admission、D binding 或公开消费者的 GO。站立授权不需重新向用户逐次征求许可，但须由主会话依据当前 source/部署/DB 事实放行一次。source、provider、真实密钥、live DB 本轮均未触碰。
- **运行时文件漂移提醒**：本 check 修改了 `live_signer_preflight.py`、`signature_topology_preflight.py` 和 README；若部署并行准备已先计算镜像 ID、源码 hash 或 pin，必须在重建前重新核对新内容。`worker_once.py` 和 B peer/TTL 均未修改。
- `.trellis/spec/backend/grounding-source-admission.md` 当前仅写到 400/gen3 的三次上限，需主会话在最终集成时同步 410 的有界第四次部署纠偏；本报告不替代权威 spec。
