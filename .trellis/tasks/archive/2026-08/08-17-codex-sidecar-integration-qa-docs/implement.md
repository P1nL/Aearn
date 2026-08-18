# 实施计划

1. 汇总 Child 1-5 的版本、测试、迁移、风险与回滚证据。
2. 建立自动化失败矩阵并补齐缺失的protocol/runtime/domain/persistence/product tests。
3. 运行feature-off Harness回归和test-only Codex plan-drafting vertical slice。
4. 执行敏感数据扫描、duplicate/stale/unsafe投影检查和process leak检查。
5. 向用户展示真实 `deepseek-v4-flash` Responses smoke边界；仅在明确批准后运行并写redacted result。
6. 执行admission关闭、active run处理、worker停止与Harness恢复的回滚演练。
7. 更新 `docs/README.md` 与相关source-of-truth文档，删除重复或过时描述。
8. 运行后端lint/typecheck/tests/bootstrap、Desktop tests/check、Trellis validate、`git diff --check`。
9. 对照父任务跨任务验收清单，记录通过、未执行或阻塞证据。

## 风险文件

- `docs/README.md` 与 Tutor Runtime/API/DB/setup/user-flow/acceptance文档
- 跨层integration tests和test fixtures
- 本地dev启动/worker health配置

## 回滚

QA与文档不改变生产流量。若集成验收失败，保持Codex admission关闭，记录阻塞场景并回到对应child修复；不删除数据库evidence。


## 实施结果

- 已汇总 Child 1-5 的协议、Runtime、typed tools、持久化、公开投影、cutover与回滚证据。
- 已完成非真实 provider failure matrix、双 Runtime scope isolation、敏感数据扫描、process leak检查与rollback验证。
- 已复用 Child 1 经明确批准的一次真实 `deepseek-v4-flash` Responses tool-repair smoke，没有重复付费调用。
- 已新增 Codex Sidecar setup与integration readiness文档，并同步 README、Runtime、API、DB、user flow、acceptance与release ledger。
- 详细结果见 `research/result.md`。
