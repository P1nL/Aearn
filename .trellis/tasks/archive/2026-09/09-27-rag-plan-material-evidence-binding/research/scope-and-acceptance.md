# D 阶段范围与证据分层（主会话核对）

日期：2026-09-27。状态：仅规划，不代表已实施或验收。

## 事实来源
- 父 phase-ii-design.md:68-78 定义反馈、binding、当前授权与发布 fence。
- 父 phase-ii-implement.md:65-81 列出真实内部消费者与 D/E 交接。
- 父 phase-ii-prd.md:38 首批 Python 核心及 SQLite SQL；RA12-RA16 是混合来源与反馈要求。
- C research/c-acceptance-2026-09-25.md:5-7、48-54 限制真实证据适用范围；既有机器回执于 2026-09-26 21:26:59（北京时间）截止，不能视作当前授权。
- 题库 09-22-multi-agent-item-bank-sandbox/task.json 当前仍 planning，无实施子任务。D 不宣称真实 item 发布消费者已交付。
- docs/README.md:33-48 指定 runtime/API/database/setup/QA 文档为 source of truth；规划不抢先更新为已实施。

## 关键约束
1. C 46 项未提交状态与当前分支保留。附 worktree-baseline.json 为路径/hash基线，不包含正文、密钥或 DSN；不是新的 Git 提交，也不替代旧会话已保存的本地检查点。
2. 本轮仅任务文件与研究文件；实现、DB、网络/provider、commit/push、消费者发布均不执行。
3. existing_only 禁止新增发现和替代搜索 provider，不禁止正常规划模型处理既有合格材料反馈。正常模型调用仍沿既有 runtime、权限和预算，不扩额度。
4. “资料足够”“corpus active”“consumer release”“item published”“Practice materialized”“Gate 完成”分开判断。
5. D 新路径使用显式内部版本开关，旧路径不换默认，不把 fixture 的合成信任提升成真实来源授权。
6. 受保护设计原型、桌面UI、旧用户 active plan、题库 owner 和正式推进/Gate均在本轮写集之外。

## D 验收层次
- D1：纯合同/选择/拒绝/不可变边界测试，默认无网络；模型替身只证明消费接缝。
- D2：专用本地临时 PostgreSQL，串行双连接授权并发、草案CAS和同事务 fence/冻结回滚；先查 current_database()，不可借用 C 真实 capture 库。
- D3：内部计划服务真实代码组合，注入确定性模型 transport，完整需求→反馈→修订→冻结；不能仅拼接 helper 后宣称 consumer 成功。
- 独立记录：真实 provider、真实当前来源、公开消费者 release、题库所有入口及完整 materialization/publication 为未执行/后续，不混入 D1-D3。

## 后续实施门禁
用户批准最终规划后才 task.py start；执行时再次核对脏树与共享写集。主会话持有 schema manifest、共享配置/DTO/plan入口集成、DB操作与文档归并，窄写集代理实现和独立检查。涉及新公开 DTO/默认路径的意外需求应先回规划，不静默扩展。
