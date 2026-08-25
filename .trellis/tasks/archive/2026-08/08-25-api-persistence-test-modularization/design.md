# 技术设计

## 持久化 package

用 `app/services/tutor/persistence/` 替代单文件，`__init__.py` 重新导出稳定公开符号。优先采用 transaction-bound mixin/facade：`PostgresTutorRepository` 持有唯一 connection，职责模块提供方法实现但不自行创建或提交事务。

建议模块：

- `contracts.py`：异常、记录与 acceptance dataclass。
- `conversation.py`：conversation、history、snapshot、cursor。
- `interaction.py`：interaction request、queue、authority receipt。
- `public_process.py`：public process 与 thinking stream。
- `run.py`：run、lease、input、checkpoint、terminal。
- `effects.py`：skill、capability、effect、provider attempt、trace。
- `curation.py`：curation/outbox。
- `mapping.py`：row/payload 编解码和通用校验。
- `repository.py`：facade、共享锁与跨职责原子操作。

跨职责方法保留在 facade，避免为了文件纯度破坏事务一致性。

## 测试目录

按领域移动测试，`tests/support/` 放共享 helper，`tests/fixtures/` 保持 fixture 数据。必要时在旧 helper 路径保留短期兼容转发，最终删除重复入口。
