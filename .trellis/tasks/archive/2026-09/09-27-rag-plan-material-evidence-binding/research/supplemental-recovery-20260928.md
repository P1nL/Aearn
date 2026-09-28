# Supplemental 授权误配置纠正：设计检查点（2026-09-28）

## 根因和边界

schema350 只对普通 attempt 放宽全局 URL 唯一索引；schema320 的 `(policy_id,generation,canonical_url_sha256)` UNIQUE 仍在。已登记的补充授权沿用原 policy/generation，因此 `take_dispatch` 的 `ON CONFLICT DO NOTHING` 拒绝，且无新 attempt / GET。该补充授权不可变且已过期；原 attempt 为 unknown，不能重试或改写。此处修复授权配置而非修改历史。

## 实施合同（先行审阅）

390 添加 append-only 撤销记录，明确引用误配 supplemental auth 和原始 terminal attempt，记录独立审批引用；原授权行不 UPDATE/DELETE。仅在该授权没有任何关联 attempt（包含 dispatched/settled/unknown）时准许撤销。新授权必须引用被撤销行、沿同一原 attempt/精确 URL，只能一次 replacement；不得链式 replacement。需用原 attempt 行锁串行化首次授权/撤销/替换与 dispatch，并保持唯一性，在 DB trigger 与 repository 双层拒绝 revoked 授权。保持 schema320 原始同 policy/gen/URL UNIQUE 和普通全局 URL UNIQUE；新 root/policy/current generation 由 operator 明确登记并核验，不自动创建或推断批准。当前旧库由主会话操作，本代理只构建代码和隔离测试，不接触实际网络/API/旧库。

## 验证门槛

新隔离 C PG：原行不变、误配未消费撤销、新 policy/root 的 replacement 只派发一次；旧 revoked 拒绝；已消费不撤销；二次替换/并发发证/撤销-派发竞争；重复 bootstrap。真实 C/D 链只由主会话执行，不以合成测试冒充。

## 落地接口与锁序

- 新 fragment `390_rag_c_supplemental_recovery.sql` 在350之后登记；独立的 `trg_00_...recovery_guard` 和 `trg_00_...recovery_dispatch_guard` 在同类 INSERT 上按名称先于350原 trigger 执行，先锁原 terminal attempt (`FOR UPDATE`)，再锁授权 (`FOR SHARE`)。撤销 trigger 同序。350单独重放只替换自己的函数/trigger，不会移除390独立守卫。迁移在安装替代守卫后才撤掉350的 `prior_attempt_id` UNIQUE；保留正常 attempt 的 `(policy,generation,url)` UNIQUE 和原全局普通 URL 部分唯一索引。
- `rag_registered_supplemental_revocations(authorization_id PK, prior_attempt_id UNIQUE, approval_ref, created_at)` 为 append-only；每条记录精确 FK 到旧授权及原 attempt。授权表增加 nullable `replaces_authorization_id`，只可引用已经持久化的撤销记录，唯一索引与原 attempt 行锁+数量/前驱判定共同禁止第二次替换或补充链。旧授权原350列值全部不变；新列对旧行应为 NULL。不能把 `row_to_json` 因 schema 新列出现 NULL 的形状改变误说成旧列被修改。
- 操作接口 `PostgresRegisteredSourceRepository.correct_unused_supplemental(*, original_authorization_id: UUID, prior_attempt_id: UUID, replacement_authorization_id: UUID, scope: RegisteredSourceScope, request_hash: str, expires_at: datetime, approval_ref: str, now: datetime) -> UUID`。必须先由 operator 独立登记当前有效且目标 `(policy,generation,url)` 无 attempt 的新 policy/root，再由其提供真实来源的 `approval_ref`；方法自己不建 root/policy、不发 grant/GET、同一短事务追加撤销及替换授权，任一步失败整体回滚。旧 auth 允许已经过期，但必须从未被派发、settle 或 unknown；新授权须未来有效。不得捏造用户签名或复用过期审批。
- `take_dispatch` 先锁当前 policy/root，再通过无锁授权读取找到原 attempt 并锁原 attempt，最后锁授权、查撤销；锁等待后重查 DB clock、auth 到期及 policy/root 当前性。SQL INSERT 附加390独立 guard 即使绕过 repository 也拒绝旧撤销授权与没有合法前驱/不匹配的新授权。`resolve` 额外查撤销；许可仍仅属同进程先前成功派发的两次检查，旧授权一旦撤销绝不能获得许可。

## 隔离验证与真实运行交接

- 使用主会话提供的显式隔离 `aearn_rag260_c_recovery_20260928`，`current_database()` 精确确认，`PYTHON_DOTENV_DISABLED=1`、`LLM_TYPE=disabled`，`DATABASE_URL` 与 `AEARN_RAG_C_TEST_DATABASE_URL` 指向同一 fixture DB。运行当前 manifest bootstrap 两遍；迁移及受影响 C repository/manifest/inventory 专项共21项通过；Ruff 和该 repository Mypy 均通过（最终执行记录可按主会话再次复核）。
- 回滚事务测试旧授权原350列未变、补充列 NULL、旧原始 unknown 无改写；误配授权撤销后旧 grant 及直接 SQL INSERT 均拒绝，新 policy/root 精确替换只派发一次；过期未消费旧授权可纠正，已消费授权拒绝撤销。并发两次纠正只有一个成功；纠正与 dispatch 竞态恰一边成功。对 populated DB 仅重放320+350两遍后，390独立 trigger 仍阻止旧撤销 grant 与第三授权；PG目录核查 trigger 排序。
- 测试中出现的 `operator.*.20260928` 是**合成 fixture 审批引用**，不代表 live 审批。主会话须在真实旧 DB 先只读确认原 attempt 与旧授权状态、当前批准和新 policy/root，再用真实 operator reference 调用此端口；本代理未修改 live DB、未执行网络/真实API、未做 C/D 真实链。若失败，不把同一数据库另开 root 当作绕过授权的一次新机会，也不改动旧审计行。

## 隔离级别与等待时钟补证

390独立 guard 在补充授权发行、撤销、补充 attempt INSERT 前拒绝非 `READ COMMITTED` 事务；原行锁在可见性更新后重读撤销和已使用状态。索引 `uq_rag_supplemental_one_original` 对 `(prior_attempt_id) WHERE replaces_authorization_id IS NULL` 保留恰一个初始授权的 DB 唯一 fence，`uq_rag_supplemental_one_replacement` 对替换前驱保持唯一；即使不可用隔离或竞态，不能只靠触发器里的 `count(*)`。测试含 Repeatable Read 三路径直接 SQL 拒绝、两个 direct initial issuance 的并行争用、撤销/派发竞争，以及持有原 attempt 行锁超过授权有效期后放行：派发二次 DB-clock 检查拒绝且无新 attempt。operator port 对目标 policy/generation/URL 已存在 attempt 先给 `CORRECTION_TARGET_SPENT`，SQL replacement trigger 同样不接收这种目标；正常原 policy/gen/URL UNIQUE 与普通全局 URL fence 未改。

扩展回归：`uv run python -m pytest -q tests/grounding tests/database/test_rag_c_schema.py -k rag_c` 于同一显式隔离测试库得到 `226 passed, 1 skipped, 597 deselected`（未把 skip 记作通过）；另21项聚焦组、Ruff、Mypy均通过。第一次使用 PowerShell 字面通配路径调用 pytest 返回 file-not-found，未执行测试；随即改用 `-k rag_c` 执行并取得上述结果。未使用 live DB。
