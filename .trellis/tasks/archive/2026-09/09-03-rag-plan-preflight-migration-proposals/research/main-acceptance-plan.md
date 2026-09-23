# Child05 独立验收计划（2026-09-23）

前置child04已本地提交a42f3e7，验收归档3a24362，无推送。继续既有child05，不新增协调任务。实现/边界子代理使用GPT-6-Sol；主代理持有运行时写入与临时数据库生命周期。

## 验收矩阵

1. 严格DTO：未知/额外权限输入、重复节点、跨Subject版本、伪造目标关闭。
2. 四态和core/optional差异；fixture_only不伪装public可用。
3. Exact corpus/source generation/hash绑定；重复提案稳定，过期源/active plan关闭。
4. 核心lc-overview不能替换为普通Python，只能blocked/wait_for_release等诚实结果。
5. PostgreSQL READ ONLY + REPEATABLE READ：真实active immutable revision，提案前后核心学习表指纹一致，无隐式事务变化。
6. Public confirm/track回归；shadow默认关闭，无API/worker/startup接入和provider/网络/操作器依赖。
7. 独立check后主代理运行相关测试/Ruff/Mypy/diff check，零连接清理临时库。

仅主代理创建的aearn_rag260_cli_preflight_20260923_1ba5e8f3允许bootstrap和合成夹具写入。原始业务数据库不写入，不读取.env，LLM_TYPE=disabled。运行时验收串行；子代理当前仅离线测试。

内部shadow和synthetic证据不是真实源接入、正式迁移、生产发布或完整学习闭环。投影式提案不等于持久化、确认或激活。
