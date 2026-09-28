# 部署 PID 拓扑与离线签名闭环修复（2026-09-28）

## 变更与结果

- 新增 `aearn/infra/rag-c-live/signature_topology_preflight.py`：固定使用已在本机存在的 r2 镜像 `sha256:0103b7…21c580`，独立随机命名 Docker 容器/卷；signer 使用真实 B `install` 和 `Attestor.handle/peer_allowed`，仅临时生成测试 Ed25519 密钥，`--network none`、真实 OUTPUT DROP。两名相同镜像的非 root 客户端分别只共享 netns 与共享 netns+PID ns，以真实 `LiveEgressAttestor` 请求新 nonce、验证固定测试公钥、4 秒到期与签名；另以错误公钥检查客户端拒绝。测试 worker 均为 65534:65534、supplementary 23456、cap-drop ALL、NoNewPrivs=1、只读。signer 保留安装规则/设置 socket/访问 peer `/proc` 所需的 NET_ADMIN、CHOWN、SYS_PTRACE；没有给 worker 权限。
- 新增 `aearn/infra/rag-c-live/live_signer_preflight.py`：仅在显式 `RAG_C_SIGNER_PREFLIGHT_ONLY=yes` 下读取独立 root-owned worker pin，复用 `worker_once.load_config/_identity/_pins`，对**当前 signer**只请求 B Unix 签名；负例使用独立 PID namespace，正例要求同时共享当前 signer 的 network+PID namespace。没有 C bridge、DNS resolver、来源 HTTP、DB 或模型路径。这是强制 pre-ARM/pre-source gate，不是自动重试/授权。
- `aearn/infra/rag-c-live/README.md` 加入可执行的离线命令、当前 signer pre-source 正反门禁、部署启动必须同时传 `--network container:<signer>` 和 `--pid container:<signer>`，并明确 pin 轮换后重验。旧三次 unknown 不更改，也不以离线通过替代新镜像/新 signer 真实门禁。

## 已运行证据

- `python aearn/infra/rag-c-live/signature_topology_preflight.py host`：两次通过，输出 `OFFLINE_EXPECTED_REJECTION:separate-pid`、`OFFLINE_FRESH_PINNED_SIGNATURE_VERIFIED`、`OFFLINE_EXPECTED_REJECTION:wrong-key`、`OFFLINE_SIGNER_GATE_PASS; NO_SOURCE_OR_GRANT_AUTHORITY`。容器日志被脚本校验：独立 PID peer 不可见/拒绝；共享 PID peer 正数、UID/GID 和 `/proc/<pid>/ns/net` 与 signer 相等；错误公钥虽获签仍在 worker 验签处被拒。脚本仅删除自己刚创建的随机名容器/卷。
- `aearn/services/api/.venv/Scripts/python.exe -m unittest discover -s aearn/infra/rag-c-live/tests -q`：40 tests OK。默认系统 Python 缺 psycopg，曾在同一测试命令下报告 3 个 import error；改用项目已有 venv，无下载/依赖安装。两个新脚本 `python -m py_compile` 通过，`git diff --check` 无错误（其他既存文件的 CRLF 警告不属本写集）。

## 尚未宣称与接线

- 此次**未启动已停用旧 live signer、未读取/使用其私钥、未请求 C grant、未发 DNS/HTTP、未接 DB 或执行新来源**。`live_signer_preflight.py` 的当前 live signer 正反验证尚未运行；需在新 signer 和独立新镜像/新 pin 已部署后，按 README 的两条 `docker run` 命令在任何 ARM/dispatch 前执行。缺一项或 signer restart/rotate 均 stop。
- 新增 `*.py` 会被 `Dockerfile.runtime` 的通配 `COPY` 纳入**下一次**镜像重建，旧 r2 镜像没有这些新文件，离线 runner 通过只读 bind 挂入，因此没有改动旧 digest。Gen4 代码变更或后续镜像重建均必须重新核对所有源 hash、image ID、签名器和控制 pin，不可使用 gen3-r2 历史 pin。正式 one-shot worker launch 必须加同一 signer 的 `--pid container:<signer>`；只共享 `--network` 的旧命令不可再用。README 的模板用新名称占位符，主会话需根据真实 `docker inspect` 审核镜像/容器/卷、负例和正例的精确退出码及标志，然后才可发任何来源许可。
