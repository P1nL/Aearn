# API 持久化与测试模块化

## 目标

降低 Tutor 持久化和 API 测试的结构复杂度，同时保持所有数据库事务、安全投影、幂等、lease、stale fencing 和测试覆盖行为。

## 需求

1. 将 `app/services/tutor/persistence.py` 拆为职责明确的 package/module。
2. 保持 `app.services.tutor.persistence` 的公开类型和类导入兼容。
3. 所有需要原子执行的操作继续共享调用方提供的 PostgreSQL connection 和事务。
4. 将 row mapping、payload 编解码、conversation、run/lease、interaction、public process/thinking、capability/effect、curation 等职责分离。
5. 将 API 测试按 tutor、learning、codex_sidecar、runners、grounding、database、integration/smoke 等领域组织。
6. 将共享测试 helper 统一放入稳定 support package，并保持 pytest discovery 完整。

## 验收标准

- [x] 原 7000 行级 persistence 单文件不再存在。
- [x] 现有生产 import 无需依赖内部模块路径，公开 API 保持兼容。
- [x] 持久化模块不存在新增隐式 connection 或事务提交。
- [x] 测试目录不再由 100 余个同级 `test_*.py` 构成。
- [x] pytest 收集数量保持 719；完整套件的外部 Celery 双消费已被测试隔离，剩余一次 Schema 重复应用 deadlock 转交数据库模块化阶段处理。
- [x] ruff、mypy、uv lock check 和 Git 差异检查通过。
