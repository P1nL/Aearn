# 计划草稿拒绝与成功后重复调用修复 — 2026-09-28

## 本轮范围与结论
按用户“快速修复，不做过多防御测试”收敛：只修真实首稿阻塞与成功后的重复生成，不扩测试矩阵、授权基础设施或公开消费者。正式配置真实模型已完成：选择 Skill → 一次 learning.plan.draft 成功 → 草稿持久化 → 回合 completed。D 整体仍 in_progress。

## 实测根因与最小修复
1. 首次新诊断实际确认 PlanningFactError：模型改写 profile.pace_summary，与已确认 pace_constraints 冲突。不是 JSON 解析错误。
2. PlanningFact 上下文增加 profile_field / copy_exact；工具 profile schema 明确 pace_constraints → pace_summary，其余字段同名，confirmed 值原样复制。validate_profile、已发布 Skill、模型输出均未改写或放宽。
3. 错误保留原 DENIED/公开码；内部只增加白名单阶段、字段和静态提示，不记录原始输入或异常正文。
4. 修复后首稿成功，随后实测发现模型同一 run 再次生成导致冲突。仅在已 VERIFIED 的 learning.plan.draft receipt 模型上下文中明确收尾指令；不修改原持久化 receipt/hash、不强制终结、不吞掉冲突。

## 验证
- 针对性纯单测：诊断与事实映射 5 passed；receipt 收尾 1 passed，共 6 项。使用不可达测试 DSN、关闭 dotenv/provider，未跑数据库测试或大回归。
- 改动文件定向 Ruff/Mypy、git diff --check 通过。独立只读检查未发现 P0/P1；未重复跑测试。
- 最终真实窗口 3 HTTP：parent_persisted / ready_for_real_successor；正常正式 Settings，非低 token 特例。
- 主会话独立只读核验专库 aearn_rag260_c_d_live_repair_01a0e0c7：terminal_outcome=completed、capability_call_count=1、唯一首稿 version=1、confirmed pace 原值保留。
- 最终首稿：8dca289e-495f-403d-91fe-833312a1ecff；目标修订 run：2831cdec-ec3f-4047-9c84-d768d0ab6cea，仅已排队、未执行。
- 本轮实际模型 HTTP 共 8 次（诊断 2 + 首稿修复验证 3 + 最终收尾验证 3），累计真实规划 HTTP 从 20 增至 28。最后声明窗口上限 29，未耗尽；没有继续重试。费用登记保留全部历史与 usage，人民币费用未知。

## 证据与保留
- plan-fact-conflict-probe-20260928.json：具体 confirmed pace 冲突。
- plan-fact-fixed-parent-20260928.json：首稿已落库但重复生成使回合失败，保留为失败证据。
- plan-draft-repair-success-20260928.json：最终成功与独立数据库核验。
- 三份完整 root-private provenance 保存在既有 Docker volume aearn-d-live-repair-01a0e0c7-d-review-gen4，文件 parent-business-probe-2045.json、parent-fact-fixed-20260928.json、parent-finalize-fixed-20260928.json，0600；未保存 provider 密钥到仓库。
- 最终 provenance SHA-256：dc1c4f8e83606e87e9da7f978a4d253652819a4d5f706fef322f228ed14e7015。

## 剩余边界
真实来源消费授权已于 2026-09-28 19:54:38 +08 到期。本轮未消费该来源、未改旧授权/到期时间、未新增取源；后续材料反馈修订、语义审核和精确绑定仍需有效来源授权后继续验收。不能把首稿成功写成完整 C→D 链通过。结束语材料语义审核仍不在本轮写集。
开发库原 19 条疑似测试记录未修改/删除。临时模型操作容器已停止，原隔离 PG、历史数据和证据保留。未 commit、push、发布或归档任务。
