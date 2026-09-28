# D closure evidence map — 2026-09-28

## 范围与证据口径

本表仅汇总 D 内部、default-off 规划教材消费。依据为既有 `implementation-verification.md`、`repair-verification.md`、2026-09-28 的真实 parent 成功记录，以及本轮 parent/successor HTTP 窗口桥接修复。既有确定性/隔离 PG 证据继续有效，但不能替代主会话即将执行的“新鲜当前 C 授权 + 真实 successor + DB 持久化”最终链。公开消费者、E、题库发布、Gate 和生产放量不在本报告放行范围。

## D-AC1..8 证据映射

| AC | 既有已证事实 | 本轮最终关闭条件 |
| --- | --- | --- |
| D-AC1 | 普通 factory、flag 关闭、缺 server opt-in/依赖均为 zero-call；旧 public/v1/shadow 路径与 import 边界已有回归证据。 | 最终命令继续保持内部显式 opt-in；不得开启公开入口或把 live harness 变成产品默认。 |
| D-AC2 | 确定性 transport 已证明 dispatcher→context→gateway→capability→plan repository→selection/binding；真实语义 reviewer 有独立正反控制。2026-09-28 已有真实 provider parent draft、completed parent run 和 pending target。 | 主会话必须证明同一真实链从当前 C selection/gap 进入真实模型 successor，并产生持久 successor、selection、binding、semantic receipt；不能只给 stdout 或 helper 成功。 |
| D-AC3 | 错 user/session/run/revision/node/goal、旧 callback、旧 selection、重复认领均有拒绝证据；合法 successor 关联可重启读取。 | 最终 successor 必须精确绑定既有 parent draft、指定 target run/input revision，且 predecessor/source 坐标、目标 hash 与 provider receipt 全部一致。 |
| D-AC4 | 既有合格资料复用、empty/partial/gap、前置依赖、cycle、错版本/用途和 existing_only 零 discovery 已覆盖。 | 当前来源只允许已审核的 `supplementary_explanation` 查询片段；`schema`、`main_teaching` 和评分缺口必须保留，不能因真实 successor 成功改写为 ready。 |
| D-AC5 | exact corpus/doc/chunk/revision/用途/授权摘要、获审 excerpt 范围及缺 claim/execution resolver 默认拒绝已有测试。 | 最终 binding 必须指向本次新鲜 capture/review/admission/corpus 的 exact 当前对象与获审片段；不得扩大到整页、main 或 assessment。 |
| D-AC6 | 同连接短事务、无 self-commit/旁路连接、代表性 policy/root 撤权与 expiry 锁序、整笔 rollback 已有隔离 PG 证据。 | 主会话需在最终读取时再次按 DB clock 验当前 policy/root/retention/admission/pointer，并证明 freeze/current authorization 属于同一持久链；无需在本轮重跑广泛 writer 竞态。 |
| D-AC7 | selection/binding 不可变、幂等/自然键冲突、target 一次认领、重启读取、purge/rollback/其他用户与 shared corpus 隔离已有证据。 | 最终 DB 查询必须能从 target run 反查唯一 successor、selection、binding、semantic review；不得手改旧行、重置计数或重绑 parent audit。 |
| D-AC8 | 离线、确定性 provider、真实组件、真实来源、公开 release/Gate 的证据层级一直分开记录。此前完整真实 C→D 链为 not_executed。 | 只有下列 DB 断言全部成立才可把 D 内部真实链改记 passed；E/公开/评分仍明确 deferred，费用未知不得记零。 |

## 主会话最终 successor 必须证明的 DB 断言

1. **数据库与时间**：`current_database()` 是本次明确的隔离 live DB；以 DB `clock_timestamp()` 证明新 policy/root/capture retention、review/admission 和 active corpus 在消费与最终复核时仍 current。
2. **不可变 parent**：parent draft 仍为 version 1、无 predecessor，user/session/conversation、source run/input revision、content hash、profile、modules/nodes/goals 与 root-private provenance 完全一致；三条实际 HTTP 对应的 durable provider receipts 保持原样且至少 source run 的 accepted receipt 存在。
3. **历史预算不改写**：parent audit 原值为 prior=25、actual=3、phase cap=4、historical cumulative cap=29；严格 parent verifier使用这些原值。不得把 parent cap 改成 34，也不得改 receipt/count 来适配 successor。
4. **显式 successor 窗口**：runner 参数必须为 prior=28、max HTTP=6、current cumulative cap=34；桥接检查 `28 == 25 + 3` 且 `28 + 6 <= 34`。结果分别输出 parent historical cap 29 与 successor cap 34；实际 successor HTTP 计数不得超过 6，项目累计按实际增加且不重置。
5. **当前 C 权威**：fresh generation 的 exact URL、Subject `route.sql`、version `sqlite-docs-v1`、facet `queries`、purpose `supplementary_explanation`、capture hash/transport proof、trusted automated review、admission、corpus link 和 active pointer 全部一致；四条旧 attempt、旧过期授权及旧 settled capture 保持不可变。
6. **target 与 successor**：指定 pending target run/input revision 最终为 completed，确有 capability 调用；唯一 successor draft 的 source run/input 等于 target，predecessor 等于 parent，版本递增、content hash 不同，全部 parent goal hashes 保留。
7. **selection/gap**：target 使用持久 parent feedback；successor selection digest 与 draft/node/goal/purpose 一致。`sql.queries/supplementary_explanation` 可 ready；`schema`、main 与 scoring 未获权部分继续显示 gap/blocked，不得删除目标来制造 complete。
8. **精确 binding**：唯一自然键 binding 指向 successor selection 和本次 current corpus/capture/review/chunk/excerpt；用途仅 supplementary，授权摘要与最终 current recheck 一致。不存在跨用户、旧 draft、错 generation 或扩用途 binding。
9. **语义 review**：存在与 target run/input revision、parent content hash、候选 attempt 精确关联的 settled `consistent/supported` review；其 provider attempt 为 accepted，reviewer model 出现在本次实际 response models。若首答错误后修复，拒绝与修复 attempts 均保留且只有获接受候选可 append/freeze。
10. **无旁路与发布**：D successor 消费事务本身不得执行 discovery/search 或 source fetch，不得手工 SQL 补稿、旧授权续命、计数清零或写入 public route/item/Gate；前置 C 来源刷新按独立单次授权执行并单列证据。只有真实 successor 全部断言通过才可输出 `passed_internal_only`、`public_release=false`。

## E / deferred 明示项

- `main_teaching` 完整 schema/queries 覆盖、`assessment_evidence` 的可信 claim/真实执行 resolver。
- 题库 item publication/materialization、真实供题与评分、学习 Gate/mastery/进度推进。
- 公开 D consumer、生产 feature flag、管理 UI/API、生产部署与生产级网络隔离证明。
- 所有自然语言/`turn_completed` 自由文本的全面语义正确性保证；当前 reviewer 只对绑定候选作概率性、有界、fail-closed 审核。
- 供应商人民币费用、余额及 300 元累计预算的精确自动核算；继续由用户人工看账单，unknown 不得写成 0。

## 本轮 harness bridge 状态

`run.py` 现以 parent audit 的原始 prior/phase/cumulative 值调用严格 verifier，再独立核对 successor prior/max/cumulative。focused offline bridge tests 为 **3 passed**，Ruff 对 `run.py` 与 `tests/test_run.py` 通过；未连接 DB、未发网络/provider 请求、未改 parent provenance、schema、source controls 或 live data。完整真实链仍由主会话按上述断言执行和定级。
