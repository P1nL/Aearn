# C 规范定位（上下文注入索引，非规格副本）

- `.trellis/spec/backend/database-guidelines.md:1074-1122` 是 260 corpus authority 的精确 code-spec：caller-owned transaction、共享表、append-only snapshot/event、first pointer CAS、合法 rollback、summary JSON 与隔离 PG/bootstrap 两次。大文件超过 context 注入上限，实施/检查时按此范围直接读取，不能只依赖其前 32 KiB 截断片段。
- `.trellis/spec/backend/quality-guidelines.md` 超过 context 注入上限；按索引找该包的质量门槛，并以 `trellis-check` 的 lint/type-check/tests/cross-layer review 为准。不要把测试 passing 视为真实许可/生产准入。
- `.trellis/spec/backend/grounding-corpus-operations.md:21-30,50-55` 的旧 operator CLI 是 fixture-only，`fetch` 返回 `FETCH_NOT_READY`，C 必须另建动态审查服务而不是让旧 CLI 声称实抓。
- `.trellis/spec/backend/grounding-controlled-discovery.md:15-52` 约束 B 持久收据、候选暂存、签名出口和默认关闭；注册 source 不能伪造 B 搜索凭据。
