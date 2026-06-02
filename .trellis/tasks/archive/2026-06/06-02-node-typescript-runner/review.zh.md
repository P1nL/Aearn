# Node TypeScript Runner - 中文 Review

## 你需要审核的结论

这个子任务实现单文件 Node/TypeScript 教学 runner，但不开放 TypeScript 公开选课。

## 范围

- 新增 `node_typescript_test` runtime tier。
- TypeScript capability 变成“runner 已实现”，但 `enabled_for_public_selection=false`。
- 支持临时目录、超时、stdout/stderr 限长、compile error、runtime error、visible/hidden tests。
- hidden case id 和隐藏期望值不能出现在 learner-facing result。

## 不做什么

- 不支持任意 npm 项目。
- 不自动安装 npm/pnpm/TypeScript。
- 不联网、不改 PATH、不改系统配置。
- 不做 SQL、Java、Go、C#、Rust、C++。

## 验收

- Node/TypeScript runner focused tests 通过。
- 现有 Python runner、M3 learning、M4 review 不回归。
- `ruff`、`mypy`、`desktop:check` 通过。
