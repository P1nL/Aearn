# 最终取源独立复核（2026-09-28，代码门禁）

## 结论

**源码代码 GO；真实 GET / 全链验收 NO-GO，待主会话独立放行。** 此 GO 仅覆盖下列已复核源码与隔离离线/合成 PostgreSQL 验证，不是 operator approval、镜像/命名空间验收、来源准入或 provider 成功证明。主会话必须重新构建并锁定已修改的 C bridge/worker 镜像、重新核对 B/C pins、root-only ARM、网络命名空间与防火墙、目标 live 库当前状态和现时授权到期；随后由主会话决定是否发出唯一最后一次 full GET。不得把本报告当成实际取源指令；本代理没有访问真实来源/模型或写 live 库。

## 独立发现与自修复

- `aearn/infra/rag-c-source-control/client.py`：原 `_roundtrip` 在 grant 和大正文 complete 使用同一个 2 秒 socket timeout。2 MiB/8 MiB base64 complete frame 的发送或 host DB settlement 回执等待超过 2 秒，会使已消耗的单次派发落入 unknown，即使 300 秒 full GET 本身成功。改为 connect/peer 仍 2 秒，只有 complete frame 发送和 settlement 响应等待为 30 秒；grant 仍为 2 秒。不存在完成后自动重发逻辑。
- `aearn/infra/rag-c-source-control/tests/test_bridge.py`：增加模拟 Unix socket 的 grant/complete deadline 差异回归；WSL Linux 本地 peer/socket 测试也全通过。
- `.trellis/spec/backend/grounding-source-admission.md`、`aearn/infra/rag-c-live/README.md`：同步 schema 390/400 授额上限和独立时间窗口，纠正 README 旧的“最长30秒”说明；B FetchLimits 的 30 秒上限不变。

## 代码路径与不变量

- `400_rag_c_final_followup.sql` 的 allowance→exact supplemental auth→attempt INSERT 三层 guard、唯一 original/latest/authorization/dispatch、原 attempt `FOR UPDATE` 序列化及 READ COMMITTED、锁后 `clock_timestamp()` 复核，使原始+第二条已消耗 unknown 仅能引出一个新 generation=3 的精确 dispatch；总 URL attempt 数为 2 时才可签发/派发第三条。390 的 correction 只用于未消费授权，final auth 的 revoke/replace 被 400 guard 拒绝；旧两行不改，第三次 unknown 也不再授第四次。对 policy/root 的共享锁阻止授权发行中并发撤权悄然越过当前检查。
- C-only long full GET：worker 明确只允许 `deadline_seconds<=300`；`SafeFetcher` 仅 registered full/redirects=0/request_gzip 时接收 override，B 的 `FetchLimits<=30` 和 B 的 wire/expanded 上限保持；正式 C wire/expanded 各<=8 MiB，full 200、exact URL、固定公网 IP、TLS peer、零 redirect。B 签名 4 秒在第二次 bridge grant 后紧贴 dial 检查，而不是要求 300 秒下载期间继续有效。
- Host bridge `_issued` 一次性 nonce 在 grant 后最多 360 秒，completion 消费 nonce；worker report 的 `pre_dial_unix_ms` 证明签名在 dial 前有效，`reported_unix_ms` 在 host 受理时仅限新近 60 秒，非 `pre_dial` 后 60 秒。settlement 以当前 policy/root、原 attempt 状态/request/hash 和 DB 时钟原子更新 attempt+capture。后续 `PostgresCurrentCaptureProvenanceResolver` 在历史 settlement 时钟重新验证 signed B envelope、worker image pin 与报告，而当前授权/保留仍单独复核；自动 SQLite SELECT reviewer 再基于完整原文和上述 provenance 作有限 claim/excerpt/usage 判断，不把来源字节扩成整页质量或 main/scoring 准入。
- 隐藏时限排查：bridge client 原2秒 complete IPC 已修；bridge server 接收每块仍2秒但不会限制两次 bridge 调用间下载时间，completion nonce=360；host report freshness=60秒从完成报告起；control ARM `expires_unix<=now+300` 只在派发前检查，不能替代新鲜现时授权；worker/report/provenance 中无额外“pre-dial 后30/60秒必须完成正文”的路径。大正文最长300秒附近仍需留有 360秒 completion/30秒 IPC/60秒 report 的真实运行余量。

## 独立验证

- 全新 fixture 库 `aearn_rag260_c_independent_20260928_01`，`127.0.0.1:55438` / `aearn_d`，先确认 `current_database()`，完整 manifest 41 fragments 连续 bootstrap 两次；仅该 fixture 库有写入。该库不含 live 来源授权，不代表生产。
- 显式 `AEARN_RAG_C_TEST_DATABASE_URL`：final-followup、scope、长正文 provenance/自动 review 专项 **24 passed**；扩大到 supplemental recovery、registered repository/bridge/provenance、B safe-fetch/pinned TLS 共 **185 passed, 1 skipped**。两组相互重叠，不累加。跳过项是测试本身的平台/条件标记，不计通过。
- C bridge unittest：Windows **16 passed, 3 skipped**；WSL Linux **19 passed, 0 skipped**，含真实本机 Unix peer/socket 的离线测试（不含公网和真实库）。
- Ruff：`app tests` 通过；C bridge `client.py`/`test_bridge.py` 通过。Mypy：`app --no-incremental` **326 source files** 通过。`uv lock --check` 通过；`git diff --check` 对 tracked 变更无空格错误。新文件尚未纳入 Git，未提交/推送。

## 真实门禁与证据等级

1. 此报告未查 live DB 当前状态。2026-09-28 13:09 checkpoint 的“两条 unknown、零 capture/review/admission/active”是历史只读快照，不能当实时事实；主会话运行前必须再次只读核对 exact live DB、原 chain、policy/root/authorization expiry 和现时 operator 意图。
2. 重新构建/哈希 C source-control 与 worker 镜像（client.py 已修改），更新并核对实际镜像 pin；重做 namespace、firewall/egress、Unix peer、B signer/TTL 与配置身份检查。另一代理的 `aearn/infra/rag-d-live` runtime preflight 不属本源码审查结论。
3. 必须由主会话单独批准 live schema400、唯一 final allowance、同库新 generation3 policy/root/dispatch/request；授权与 URL/Subject/version/facets/用途/8 MiB、期限逐项精确检查。旧 350/390 已消费权利不可复活。若 GET 失败/unknown，不开启第四次，也不换库重置次数。
4. 真实 C capture→独立可信自动审核→exact WHERE/LIMIT supplementary admission→D 真模型 parent/successor/selection/binding 必须在**同一真实链**留证。未覆盖的 schema/main/scoring 仍 gap；与真实 provider usage、失败和费用未知项分别记录。公开消费者/E/item/Gate 不在本门禁放行范围。
