# 上下文预算断言修复（2026-09-27）

## 结论与证据

隔离 PostgreSQL 测试库 `aearn_repair_d_budget_20260927` 已完成 manifest 双次 bootstrap；仅在此库执行目标测试，未调用真实模型。原 `test_small_provider_budget_still_rejects_artifact_before_provider_or_writes` 在 4096 输入上限下失败：返回 `completed`，并非预算代码漏检。用**仅本次 Python 进程内**的 `TutorContextBudgetPlanner.build_context` 包装探针读取同一 PG 测试流（探针没有落盘，也没有修改生产模块）：必需 context selection 为 339 估算 token，实际序列化必需请求连同 protocol/safety reserve 为 3705；两次 provider 前完整请求估算分别为 4049、3916，均不超过 4096。探针不输出材料或私人内容。另有离线代表性教学候选测量：3072 报 `TUTOR_CONTEXT_REQUIRED_OVERFLOW`，3584/4096 可选入，支持阈值随上下文改变而非固定为 4096。

根因是旧测试把“4096 必然溢出”的历史体积假设写死；当下 compact teaching projection 和精确序列化下，当前 fixture 的必需内容能够完整容纳，不能为了让旧断言通过而扩大估算、压掉 required facts 或让 provider 误拒合法输入。生产预算器 `_estimate_complete_request` 仍对完整序列化请求加 protocol/safety reserve，`_stabilize_estimate` 在超过硬上限时拒绝；本次未发现这条路径的生产缺陷，未改 `context_budget.py` / `context_builder.py`、默认 4096 conservative cap 或 D required-facts 的 8 项/1200 字符边界。

## 有界修复

修改 `aearn/services/api/tests/learning/test_catalog_artifact_scope.py`：负例将此 synthetic provider 的**局部** input limit 收至 3500（固定输出 reserve 4096 不变），仍断言 `TUTOR_CONTEXT_REQUIRED_OVERFLOW`、provider 零调用、artifact 零写；新增 4096 正例，断言正常完成、provider 使用 exact handle 并创建一个 artifact。两例均用进程内测试 spy 捕获当前真实请求的 serialized required floor（含协议/安全 reserve），断言 `3500 < floor <= 4096`；正例还核对每次完整序列化估算不高于 metadata 记录、不高于 4096。没有把失败改成 skip，也没有降低拒绝/零写断言。3500 是由此 fixture 的已测 floor 而非猜测阈值选定，不改变真实 Settings 默认容量；若将来 serializer/facts 缩小到能放进 3500，测试会失败并要求重新审查场景。

另在 `tests/tutor/test_tutor_context_budget.py` 增加无可选内容的离线精确边界测试，按实际序列化请求在固定 500..4096 区间二分查找最小可容纳输入上限，验证 selected required fact 完整、实际序列化字节估算加两种 reserve **恰好等于**该上限、低一 token 必须 `TUTOR_CONTEXT_REQUIRED_OVERFLOW`。本次运行找到 exact-fit 2510 / 2509 拒绝；该数字不硬编码到测试，后续 prompt 改动会由同一边界性质复验。

## 验证

- 修复前：目标 PG 用例 1 failed，`diagnostic_code=None`、`completed`；内存探针记录上述数字。
- 最终合并运行：`test_catalog_artifact_scope.py` + `test_tutor_context_budget.py` + `test_teaching_context_candidate_compaction.py` + `test_rag_d_parent_context.py` + `test_tutor_context_builder.py`：**43 passed**（隔离 PG + 离线），含低预算前置拒绝、4096 正例、exact-fit/低一 token 边界及 D 完整 parent/material required-facts。
- `ruff check tests/learning/test_catalog_artifact_scope.py tests/tutor/test_tutor_context_budget.py`：passed；目标 diff `git diff --check`：passed（Git 报 LF/CRLF 工作树转换警告，非内容错误）。

未执行全库测试，也未把该预算负例等同于真实 provider/E 公共发布验收。`provider_gateway.py` 当时由并行工作变脏，本切片没有写该文件；临时 Python 导入不改变磁盘内容。主会话完成共享集成后可复跑本文件及更广回归。
