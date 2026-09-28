# P1 独立复核（2026-09-27）

范围仅限 `material_contracts_v2.py`、`material_binding_repository.py`、`370_rag_plan_material_bindings.sql` 与 P1 专项测试；P2/P3/P4 并行写集不作本报告的验收。未接数据库或 provider，未提交、推送、归档。

## 已修复

1. Selection 的 ready 前置条件原按「相同用途 ready」查找，补充讲解 ready 可在主教材前置节点未 ready 时宣称下游 ready。现按前置节点的 `main_teaching` ready 判定，与学习侧依赖投影一致；加入纯合同回归。
2. Selection entry 允许重复的 exact evidence，可能把同一片段计为多个证据。现按 canonical coordinate digest 拒绝重复，加入纯合同回归。
3. Target run 只验 terminal receipt 为空；数据库可存 `status='failed'` 而 receipt 仍为空。现 assignment 与反馈读取均要求非终态状态、无已产生的同 run/revision 草案，并要求 target run 不早于 parent draft；加入隔离 PG 回归（待主代理串行运行）。
4. Pending snapshot 初次入库查真实作业，但 assignment/restart read 未复查；作业已终结仍可作为 pending 反馈。现两个读取点再次核对 exact pending/leased job；加入隔离 PG 回归（待运行）。
5. 补充隔离 PG 断言：局部 target assignment、普通/错用户 purge、已赋值后改 target revision 均被拒绝；正确用户的事务内 purge 可删除用户级 selection。PG 测试尚未由本代理执行。

## 核对结果与边界

- `record_selection` 按现行 draft/session/user/version/hash、整稿节点集合、goal/prerequisites 和 pending job 核对；回放走同一验证。
- `freeze_binding` 要求 exact ready entry/evidence 和当前 receipt；同草案自然键唯一约束阻断换 retry key 冻结另一证据。纯合同对 nested copy 重验、None/bool/错 digest receipt 已有测试。
- Schema 一次 NULL→target 的 trigger、target pair 唯一、binding 自然键、scoped FK、用户级 purge GUC 已核对。本轮没有改 schema 形状，无需因本轮修复重建库。
- P1 哈希与 caller-injected receipt 是完整性/接口合同，不构成 C 当前来源真实性证明；P2 受信 adapter 和双连接 fence、P3 真模型接线、P4 reset/delete、E 题库入口以及当前真实来源/付费 API 均不在本次独立验收。
- `.trellis/spec/` 的 D 新规范需主代理在 P5 以最终集成事实统一同步；本轮不并发抢写 spec。

## 验证

- 离线 pytest（P1+相邻 P2/P3 纯测试）：13 passed、14 skipped（PG 未设 disposable URL）。
- Ruff：P1 五个 Python 文件通过。
- Mypy：P1 两个业务模块通过。
- `git diff --check`：通过（仅现有文件换行警告）。
- PostgreSQL：**未执行**；新加的 pending job 状态迁移、purge、assignment/freeze 测试待主代理在新/现行合格可丢弃 D 库中串行运行。已有主代理先前的 PG 通过结果不覆盖本次新增断言。

## 共享依赖规则补丁（主会话交接）

- `material_contracts_v2.py::apply_material_dependencies(requirements, entries)` 是 P1/P2/P3 唯一纯依赖归一入口：先验证整图未知前置、环、重复/不一致 node/goal/要求与 entry key，再按前置节点 `main_teaching` 的传递 ready 计算。输入的 entry 顺序可任意；输出按 requirements 顺序。被阻断项改为 gap，追加 `prerequisite_blocked` 而不覆盖原有缺口，保留证据/覆盖；清空与非 pending 状态不兼容的 job handle。strict `MaterialSelectionResult` 对未归一结果拒绝，不自行默许。无 DB/type/schema/公开 API 方法签名变化。
- 纯回归覆盖乱序、传递阻断、已有缺口和证据保留、未知前置/环/缺成员、strict result 拒绝未归一。
- 修正新增 PG pending fixture 的 JSON dict/list → strict Pydantic 错误：使用 `model_validate_json(json.dumps(...))`，不放宽合同。主代理上一轮报告 P1 新增 PG 为 20 passed/1 failed（此 fixture）；本代理未连库，该修复待下一轮主代理复验。
- 最新本地离线子集：13 passed、7 skipped（PG 未启用）；Ruff/Mypy 通过。上一段离线计数为修补前的另一组选定文件，不作为这次 helper 的验收计数。
