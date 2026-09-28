# C 补充纠正与 gzip 的独立 live-preflight 复核

## 结论（交 operator 前）

**代码门禁：GO；真实 390 写入与一次 GET：目前 NO-GO，待主会话完成现场只读核验与批准。** 本次只在指定新隔离库验证迁移与合成记录，未连接旧 live 库、未发 DNS/HTTP/模型请求、未构建或核对真实 worker 镜像与 pins。离线测试通过不是旧库当前授权、审批引用或安全隔离的证据。operator 不得把此结论视为一次额外 dispatch 许可。

未发现本次窄范围内可复现的 P1 代码阻塞，未改业务代码与 app/tests。实施前必须由主会话/实际 operator 在真实目标库只读确认：数据库身份；原 attempt 仍为 terminal unknown/settled、原始列未变且没有 supplemental id；误配置 auth 仍为原始、从无任何关联 attempt（含未知/已结算）；该原始 URL 的准确 SHA；目标 policy/generation/root 当前有效且该 `(policy,generation,url)` 无 attempt；有效的新独立 approval_ref 与新 dispatch/request 坐标。不可借换库、换 URL、改旧行、沿用过期审批或原 unknown 再派发绕过一次性边界。写入应仅一次短事务调用 `correct_unused_supplemental`，写后复读 old/revocation/replacement 三者，再决定是否派发。

真实 GET 还须另行确认新 image/code hash、B/C pin、签名 egress/namespace/firewall、精确 C scope 与两个当前 grant、许可/保留期限及无其他在途 worker；新镜像和 operator 环境准备尚未由本 reviewer 验证。一次调用失败或结果 unknown 后仍不得重试/再纠正，不得以 curl/partial 充当 full。C 自动审核、D 真实 provider、binding 必须各自留存独立证据。

## 代码路径核对

- `390_rag_c_supplemental_recovery.sql` 的 revocation 为追加表，旧授权原 350 列不 UPDATE/DELETE；新 nullable `replaces_authorization_id` 对旧行为 NULL。审计旧行只能比较旧列投影，不能把 `SELECT *` 因新增 NULL 列而形状变化误认为旧值被改。原 attempt 的旧列/terminal 状态同样不改。
- 三条新 guard 对 issue/revoke/dispatch 要求 READ COMMITTED，先锁同一原 terminal attempt；单原授权部分唯一索引、单 replacement 唯一索引和数量校验限制仅一次纠正。350 旧 guard 与 390 独立 guard 同时保留，新 `trg_00_` 先于旧 `trg_` 执行。320 同 policy/generation/URL 唯一约束与 350 普通 attempt 的全局 URL 部分唯一索引仍在；重放 320→350 不能移除 390 独立 guard。
- `correct_unused_supplemental` 在同事务先核新 policy/root 与时间，锁原 attempt/旧 auth，拒绝原 auth 已 replacement、原 attempt 已 supplemental、目标 `(policy,generation,url)` 已有 attempt，再追加 revoke + replacement；失败整体回滚。旧 revoked auth 在 repository 和 SQL INSERT guard 均不能派发；已消费 auth 不能撤销。`take_dispatch` 等锁后复核当前性/到期，许可仅派发成功实例持有，不能由持久 attempt 重新获得。
- C worker 唯一显式启用 `request_gzip=True` 且 scope 仍 full GET/零 redirect；B 默认请求头不变，HEAD/prefix 不协商 gzip，Range 固定 identity。连接器的允许请求头与实际 wire 格式一致；流式解码分别限制 compressed/expanded bytes，检查 gzip eof、尾随第二 member、截断、Content-Length 与实体 hash，失败不返回部分 full body。deadline 与许可不被放宽。

## 独立验证

- 连接指定 `aearn_rag260_c_recovery_check_20260928`，`current_database()` 精确相等、初始无 C 表；`PYTHON_DOTENV_DISABLED=1`、`LLM_TYPE=disabled`，DATABASE_URL 与 AEARN_RAG_C_TEST_DATABASE_URL 同指该隔离库。`apply_schema` 完整 manifest 连续两次提交成功；PG catalog 确认三个新唯一索引和两个 `trg_00_` guard 存在。
- 合成 PG 纠正测试实际覆盖旧 350 字段逐值不变及新列 NULL、旧 auth/直接 SQL 拒绝、目标已花费拒绝、已消费拒绝、并发发证/撤销与 dispatch 二选一、RR 直接 SQL 禁止、等锁后过期拒绝、320→350 重放、完整 manifest 重放。运行 `tests/grounding -k rag_c`：224 passed、1 skipped、597 deselected；DB schema/manifest：7 passed。该 skipped 未被计作已验证，合成审批引用不是真实审批。
- 独立组合专项（recovery、registered repository、schema manifest、B safe-fetch、pin TLS、C worker）：127 passed、24 subtests passed；所涉 Ruff 全绿、三个核心源文件 Mypy 全绿。`git diff --check` 涉及已跟踪 gzip 文件未见空白错误（Git 的 LF→CRLF 提示不是检查失败）。

## 保留限制

这是代码与隔离迁移预检，不是 live 授权签发、GET 成功、C 审核通过、D 绑定或公开消费者验收。当前真实旧库内容、实际审批、镜像/pins/网络隔离未由本 reviewer 检查；在上述现场条件完成前，不给实际写入/GET 放行结论。