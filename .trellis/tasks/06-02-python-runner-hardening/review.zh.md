# Python Runner Hardening - 中文 Review

## 你需要审核的结论

这个子任务只强化现有 Python runner，不做 Node/TypeScript、SQL、Java、Go、C#、Rust、C++。

## 范围

- Python sandbox subprocess 改为在临时目录执行。
- runner 输出继续限长。
- 函数调用期间的 Python 异常要返回 `runtime_error`，不能伪装成 `success`。
- hidden test 的原始 case id 和失败细节不能进入 learner-facing `test_results`。
- 可见测试失败仍保留有用反馈。

## 不做什么

- 不引入 Docker/container 沙盒。
- 不改数据库。
- 不实现其他语言 runner。
- 不把 Python sandbox 说成 OS/container 级隔离。

## 验收

- `tests/test_sandbox.py` 和 `tests/test_runner_registry.py` 覆盖临时 workspace、hidden redaction、runtime error、stdout bounding。
- `ruff`、`mypy`、`desktop:check` 通过。
