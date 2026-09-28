# D 语义修复实施检查点（2026-09-27，未验收）

供主会话协调，实时工作树非提交快照。此文件不是 passed 报告；此前独立真实 DeepSeek 修订探测也不是完整 D 产品调用。

## 已落接口与当前写集

- `learning/material_semantics.py`：参照既有 `practice/model_review_semantics.py` 建 D 专用严格 `consistent/inconsistent/uncertain` verdict、闭集原因、run/selection/parent/candidate 哈希绑定、无全文落盘的 review request/receipt；`PrimaryMaterialSemanticReviewer(settings)` 以显式 Settings 构建 `OpenAICompatibleClient(..., max_http_attempts=1)`，一次 256 输出 tokens、20s、thinking disabled。reviewer 完整消息先调用 `assert_tutor_provider_request_budget`；uncertain 不认可。
- `learning/material_selection.py`：保留原 D 可修改的计划字段、goal/node 等确定性校验；新 `review_decision` 针对真正 `learning.plan.draft` 候选短事务加载原 parent/完整 selection、事务外 review、再短事务核 run lease/revision 与 selection 并记录 verdict+usage；`assert_review_before_append` 从已存 selection/parent 重新计算 authority/candidate/binding 哈希并要求当前 run 的 consistent receipt。skill select/terminal 消息不新增一致性 receipt。
- `learning/material_planning_composition.py` + `tutor/interactive.py`：仅双闸 D 注入 reviewer/同连接 consumer/provider binder；原生产 factory 的空注入路径不构造 reviewer。Primary gateway 内部两次候选修复循环；确定性测试 provider 仅有拒绝式 wrapper，不伪称提供第二次模型修复。
- `tutor/provider_gateway.py`：可选默认 None 的决策验证钩子；按现有最多两次候选，reviewer inconsistent 返回安全 issue，uncertain 不重试；在添加修复指令之后、每笔 `complete_json` 前检查完整请求预算，超限 FAILED、保留已有尝试、不新增请求。
- `llm/llm_client.py`：单实例 `max_http_attempts`，默认原 3 不变，reviewer 实例设 1；无全局常量修改。
- `db/schema/380_rag_material_semantic_reviews.sql`：私有 append-only 审查 receipt、run/user/conversation 与 selection FK、同 run/revision 唯一 consistent；schema manifest 登记及 reset/delete inventory/purge 顺序增加审查表，在 selection 删除前删审查表。

## 已检查与尚未通过

- 当前新增/修改 Python 文件编译、Ruff 通过；`test_schema_manifest.py` 5 passed；专属 `aearn_rag260_c_d_repair_20260927` PG 执行完整 manifest 两次曾成功，但此后新增 380 authority/candidate 哈希列，必须重新 bootstrap 两次验证。
- **未完成** D PG 实际路径测试。旧 D dispatcher 测试使用无 reviewer 的假 provider，须注入确定性 reviewer 并重跑；首轮合法 JSON 误解 SQL WHERE 为学习地点→第二轮修正、两轮耗尽→无 successor/binding、uncertain/usage、wrong-run/digest/lease/CAS、purge/reset/delete 尚待新增或回归。
- `learning/material_selection.py` 中新 D 审查 SQL、run lease/current selection 顺序和 append receipt 的实际 DB 执行尚未测试；可能有 FK、status、usage JSON、idempotent replay 或上下文上限问题。现有反馈继续是前 8 条的提示摘要；reviewer 通过同连接重新读取**完整** selection/parent 并自身按请求预算拒绝过大事实，不能把提示摘要冒充 review 全量输入。
- 须确定性 provider 真实 gateway transport 测试检查 repair issue 与尝试次数；主会话的预算独立测试验证 gateway 超限停止。真实 C 来源和真实 reviewer/provider 验收另列，不能由合成测试替代。
- 目前 `research/semantic-repair-design.md` 是批准方向；最终真实结果须更新 `research/semantic-repair.md`。不触碰 C authority/公开 DTO、未用 API key、未收费调用、未提交/推送。
