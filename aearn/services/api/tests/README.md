# API 测试目录

测试按主要责任边界分组：

- `tutor/`：Tutor 对话、状态、持久化、教学与主动运行。
- `learning/`：学习计划、课程、练习、复习与模型评审。
- `codex_sidecar/`：Codex sidecar 协议、适配、投影与 cutover。
- `runners/`：sandbox、语言 runner、执行队列与执行安全。
- `grounding/`：来源注册、抓取、处理、检索、引用与索引。
- `database/`：数据库 bootstrap 与 schema smoke。
- `integration/`：跨领域集成、健康检查与 worker 装配。
- `smoke/`：显式环境开关控制的 smoke 与 real-provider 测试。
- `support/`：跨测试模块复用的 fixture 与构造 helper。
- `fixtures/`：静态 fixture 数据和 fake protocol server。

从 `aearn/services/api` 运行 `python -m pytest`；不要依赖当前测试文件位于测试根目录。
