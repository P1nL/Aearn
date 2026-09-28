# C 第四次有界部署纠偏授权（2026-09-28）

## 事实与决定

在隔离的真实 C/D 验收库 `aearn_rag260_c_d_live_repair_01a0e0c7`，原始 dispatch `0ffc109e-136b-4b99-b270-2896f8d92edd`、第二次 `9ab67b2d-4d62-47be-8ae0-4df576b099e9` 均保留 `unknown/DEADLINE_EXCEEDED`，第三次 `c3cae434-cd25-47b9-b26a-1459e2dc3aa3` 为 `unknown/EGRESS_UNVERIFIED`。第三次发生在签名/egress 阶段，未证明目标 HTTP 完成，capture/review/admission/corpus 为零；已花费 dispatch 不可重试。以上是忽略的 `live400-attempt-result-20260928.json` 的只读历史记录，不是新网络授权或来源审核。旧 350/390/400 allowance、auth、attempt、policy/root 原字段/到期不改。

用户重申项目持续授权并要求执行；由主会话决定新授权及唯一后续真实 fetch 的 GO。此代码**只准备**一个独立、operator-only 的 generation 4 有界纠偏，不自动签发任何行、不触发 HTTP/模型。主会话部署负责人单独修复 peer topology；代码通过并不证明部署隔离或源页面许可。没有旧 token/ARM 的别名重播或第三次余量。

## 授权合同与审计

- 410 增量迁移重用 `rag_registered_final_followup_allowances` 和 `rag_registered_supplemental_authorizations`：允许同一 original 各一条 generation 3/4 immutable allowance，保留旧行；generation 4 精确绑定新 policy/root/dispatch/request hash/URL/current expiry/approval ref 与**同一 original**，latest 必须是该 original 的 generation 3 final allowance 所签发的第三次 attempt。三次原始尝试均须 terminal `unknown`，且同 URL 当前累计正好三次，generation 4 issue/dispatch 在 `READ COMMITTED` 以 original `FOR UPDATE` 串行；无第五次额度、无自动循环。
- 新 generation 4 policy/root 必须单独当前有效，原 Subject/version、facets、source handle、exact URL/host/path、用途相等；byte cap 不扩大。历史授权时效不延长；新有效期不得越过新 policy retention/expiry、root delegation/period。旧用途仅 `supplementary_explanation`，不得升级主教学或评分。缺失、撤权、到期、错原始/第三次身份、重放、已用 dispatch 均失败关闭。
- 申请者填写并审核 `approval_ref`（项目 standing policy + deployment correction 操作审批），新 UUID 与 request hash；不能由失败异常自动铸造。仅在主会话核验代码、部署签名/egress、当前 DB 时钟、权限/来源和独立 review 后签发一次。任何新真实 fetch 必须另过 main 的单次 GO；没有此 GO 不使用新 credit。
- 仅在自建 `127.0.0.1:55438` 的 `aearn_rag260_c_410_01a0e6b8` 测试库做合成行验证，dotenv/provider 关闭；不连接 live C DB、不发网络请求、不调用模型。完整 bootstrap 两次、专项与原 generation 3 回归、schema manifest、Ruff/Mypy 验证记录由本代理另报。

## 未解决边界

当前 live DB 尚未应用 410、未生成 generation 4 policy/root/allowance/auth/dispatch，主会话需在部署修复与独立签核后以只读 fresh inventory 确认上述历史；如果真实第三次状态、来源用途或时效不符，拒绝新 credit，不改旧行。即使真实抓取成功，C 的可信审核/准入、D 真实模型 successor+binding、E/公开发布仍分别验收。

## 实施验证（仅合成测试）

在 `127.0.0.1:55438` 的专用 `aearn_rag260_c_410_01a0e6b8` 库确认 `current_database()`，完整 bootstrap 两次成功。2026-09-28 执行 `test_rag_c_registered_source_repository.py`、`test_rag_c_deployment_correction.py`、`test_rag_c_final_followup.py`、`test_schema_manifest.py`：**33 passed**。含历史 gen3 正例、gen4 精确链/旧行不变/重复授权与第五次拒绝、错原始与 latest、用途扩大、过期、错 URL/root/approval ref、第三次非 terminal unknown、完整 manifest 双重重放。相关文件 Ruff 通过，repository 单文件 Mypy 通过，`git diff --check` 通过（仅现有工作树 LF/CRLF 提示）。这些测试不是 live DB、新来源 HTTP、deployment egress 或生产审核证据。
