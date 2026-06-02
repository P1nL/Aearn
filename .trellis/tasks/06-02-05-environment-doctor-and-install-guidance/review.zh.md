# 05 环境医生与安装指导 - 中文 Review

## 你需要审核的结论

这个子任务要做的是：在 Aearn 本地桌面产品里接入“环境医生”，让设置页能看到当前机器的 API、启动脚本、Python、uv、Node、pnpm、Docker、JDK、Go、.NET、SQL/数据库相关工具状态，并给出静态、白名单内的 Windows 优先安装指导。

## 范围

- 后端新增 `GET /api/environment/doctor`。
- 后端返回检测事实、语言 runner 矩阵和静态指导模板。
- 前端 settings / 诊断页展示这些信息，并提供刷新。
- 检测只读版本命令和文件存在性，不执行安装、不改 PATH、不动 Docker/WSL/系统设置。

## 关键边界

- TypeScript、SQL、Java、Go、C#、Rust、C++ 即使本机装了工具链，也不能显示成“Aearn 已可执行”。
- 安装指导可以展示手动命令，但产品和 Agent 不能自动执行。
- 不接 live web search，指导来自代码里的静态模板。
- 不改数据库、不加 runner adapter、不启动后台任务。

## 验收点

- API 返回 summary、components、language_runners、guidance。
- 缺工具或命令失败不会让 API 崩溃，只会返回 `missing` / `error`。
- 设置页能展示环境状态、runner 矩阵和对应指导。
- 现有 health、language capability、runner registry、desktop check 继续通过。

## 实施顺序

1. 先用 fake command runner 写后端测试。
2. 实现 environment doctor service。
3. 加 API route 并接进 FastAPI。
4. 前端增加类型、API fetch、settings 展示。
5. 跑 focused backend tests、`ruff`、`mypy`、`desktop:check`、Trellis validate。

## 风险

- 如果把“检测到工具链”误认为“runner 已实现”，会造成产品 overclaim。
- 如果检测函数执行安装或改系统配置，会越过本地产品安全边界。
- 如果前端直接相信任意 payload，可能在 settings 页显示错误状态；所以需要 fetch boundary guard。
