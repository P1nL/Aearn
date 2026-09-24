# A 包独立就绪复核（规划静态核对）

日期：2026-09-24。结论：**PASS，仅 A 离线合同包的规划就绪**。本次仅复核上次提出的三处合同歧义：子 PRD/design 与父 phase-ii-design 的修订；未检查代码、未启动任务。用户对 A 和必要公开来源核对的既有批准有效，**无需重问同一 A 授权**。

## 三处澄清的复核

1. **发现需求签发边界：已澄清。** 子 design §分层接口与子 PRD §需求把 `SourceDiscoverySuggestion` 列为无权限的模型建议，`SourceDiscoveryDemand` 则由服务端验证后签发去身份化查询投影及受信 actor/policy/canonical 预算委托；父 phase-ii-design §3 已同步拆分。模型不能自报 actor/root/余额或把候选 URL、search receipt 变成探查权。
2. **DTO/resolver 与真实 authority：已澄清。** 子 design §A不承诺的能力及§关键设计明确 A 只定义静态 DTO、纯判定与只读 resolver 协议，缺真实 authority 默认拒绝；合成 server context 正例仅证明判定规则，不是 B/C 的实际验真、预算预留、来源准入、claim 核验或签发 receipt。binding 的实际消费仍由 D/E 交付。
3. **关闭路径验收范围：已澄清。** 子 PRD AC6 和 design §关键设计只要求 A 新增纯逻辑及 port 的四开关独立默认 false、关闭路径无外部调用；不声称既有 CLI、runtime、consumer 已接新 gate。B/C/D 实际入口的强制门禁须在对应阶段另验。

## 审批、探查与交付边界

- `research/user-approval.md` 仅覆盖 A 与必要的公开来源搜索/读取，不授予 B–E、付费/私人内容、生产写入、逐 scope 发布或部署权限；当前仍为 planning。
- main 的 `research/bounded-public-probes.json` 是四个公开 URL 的有限读取元数据，其中 capped 响应仅有前缀 hash；它既不是 A runtime 搜索/抓取实现，也不证明完整正文、生产 SSRF/egress 防护、许可、corpus 准入或 claim 验证。
- 原先三项阻塞均已解除；这只是**按已批准范围进入 A 离线实施准备的规划判断**，不是 A 已实现、测试通过、真实来源已审核或产品可发布的结论。后续 B/C/D/E 的真实权限和证据仍需独立处理。

## 验证

静态文档复核；Lint：未运行；TypeCheck：未运行；Tests：未运行（本轮无代码变更）。未执行新的网络、DB 或 provider 操作；未 task start、未提交。
