# Research: 三任务联合 W0 合同核对

- Query: 仅核对既有 RAG／题库／小节推进规划的 scope、version、coverage、owner、预算接缝；不审并行实现代码。
- Scope: internal
- Date: 2026-09-23

## Findings

### 文件与定位

- `.trellis/tasks/09-22-multi-agent-item-bank-sandbox/research/execution-acceptance-roadmap.md` — W0–W5 顺序、单写者及 G0–G4 联合验收。
- `.trellis/tasks/09-22-multi-agent-item-bank-sandbox/prd.md`、`design.md` — 供给／覆盖 proof、执行型 Gate 适配和 canonical 预算。
- `.trellis/tasks/09-22-multi-agent-item-bank-sandbox/research/progression-supply-boundary.md` — 冻结 demand/result 的字段与状态草案。
- `.trellis/tasks/09-21-lesson-progression-closure/design.md` — 正式目标、Gate/Attempt、教学及结束 authority。
- `.trellis/tasks/09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md` — RAG 阶段 II 来源治理、证据绑定和授权 fence。
- 参考既有 `.trellis/spec/backend/learning-item-bank-governance.md:5-7,58-71` 及 `aearn/services/api/app/services/learning/practice/gate_selection.py:72-99`：当前 Gate 选择仍是 published KC/capability 过滤，不是假定已有 objective coverage/SQL 执行适配；本次未审并行 child 代码。

### 已一致的合同

1. **单一 authority／先后次序一致。** RAG 管 Subject/version/source/corpus/facet，题库管 item 发布及 objective proof，推进管正式 Gate/Attempt/progress；真实来源准入、item 准入和正式通过互不代替。对应 roadmap §1–3/G1、题库 design §1/§7/§10、推进 design §1/§9、RAG 扩展 §1/§7/§8。共享 `practice/repository.py`、`practice/service.py`、`practice/gate_selection.py` 串行单写，非三个任务并改。
2. **覆盖／版本一致。** 题库 `ready_exact` 必须匹配冻结 scope/objective/assessment/capability 及 immutable item/proof，推进仍复核并由 Gate prepare；RAG 证据只证明来源 facet，发布前要当前授权复核与 generation fence，不能替代目标 proof。对应供给边界 §4–5（尤其 :129-135、:140-186）、题库 design §4/§10、推进 design §2/§5、RAG 扩展 §7。旧供给研究 :132 的“签发者待定”已由较新的题库 design §4（:69-71）明确为覆盖验证服务；不是仍开放的冲突。
3. **预算／支持口径不冲突。** 题库 canonical root 键包含 objective、用途/执行合同、visibility/policy，RAG 子作业按 Subject/version/source-policy/gap 建根并保留题库父需求因果链，子费用计入全局池且仅结算一次；二者不是应当相同的 root ID。对应题库 design §11–12（:211-213、:221-252）、RAG 扩展 §5（:64-70）/RA9、roadmap W0/G4。推进的“每目标诊断最多 2 次＋补救 1 次”是教学防重复，不是题库 D7 模型讨论/修订轮次（推进 design §3；题库 design §12）。公开 8 课程 ID 中 `html_css` 与 9 语言 ID 的 `html`、`css` 口径不同，不视为覆盖差错；旧文档 GPT-5.6-Sol 调度表述以本轮明确 GPT-6-Sol 指令为准。

### W0 接口须先钉牢（不阻断当前 Subject child 的独立实现，但阻断后续真实接线）

1. **课程目标到 RAG Subject/version/facets 的服务端映射尚无共同键。** 题库需求草案冻结 assignment/document/objective/capability，却未声明供给侧如何由这些字段确定唯一的 `subject_id/version` 与 required facets、如何把该映射纳入 demand hash/stale 判断；RAG typed 后台需求只能接收 server-resolved Subject/version/facets，不能让模型/consumer 任选 URL 或版本。需在 W0 明确映射的 owner、失败状态以及版本变化时的重取证／stale 规则，否则 W2–W3 有“题目目标 exact、资料却取错 Subject/version”的接线空位。定位：roadmap §2 W0/W2–W3；供给边界 §4（:85-131）；题库 design §10（:165-175）；RAG 扩展 §3（:35-37）/§7（:82-93）。这是**尚未冻结的跨任务转换合同**，不是发现当前 child 代码错误。
2. **`pending` 不能沿用正式 Attempt 的 `waiting_result`。** 供给边界 §5/§7（:140-186、:210-214）允许 `pending` 映射为 assessment “unavailable/waiting”；推进 design §2/§4（:21、:46）已把 `waiting_result` 留给正式异步 Attempt terminal 回执。W0 需把“待供题（无 binding/Attempt）”与“已提交待正式评分（有 binding/Attempt）”的消费侧状态和恢复键分别固定；否则 UI/replay 可能把生成作业等待误当已作答等待。可使用 `unavailable` 附准备原因，但不得凭 `pending` prepare/计分。定位：roadmap §2 W0/§3；推进 design §6（:62-72）；供给边界 §5。

## Caveats / Not Found

- 未发现上述指定文档之间有使当前 RAG Subject child01 必须停工的 scope、owner 或预算硬冲突。两处是后续消费者接线前须冻结的 W0 空位，未声称测试／真实来源准入已经完成。
- 本次仅静态读取指定五类任务规划文档、相关既有 spec 与一处旧 Gate 选择入口；未运行服务、DB、provider、浏览器或测试，未读取/修改并行 child 实现。External references：无。
