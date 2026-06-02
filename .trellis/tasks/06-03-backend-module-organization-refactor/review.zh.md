# Backend module organization/refactor Review

## 目标

把 `aearn/services/api/app/services` 和 `aearn/services/api/app/agents` 从大平铺目录整理成更清晰的领域子包，方便以后找文件、维护 runner、grounding、conversation、repository 和 Agent 代码。

## 范围

- 整理 `app/services`：建议拆成 `conversations`、`curriculum`、`environment`、`exercises`、`grounding`、`llm`、`repositories`、`runners`、`streaming`。
- 整理 `app/agents`：建议拆成 `graphs`、`learning`、`notes`、`onboarding`、`review`、`runtime`、`tooling`。
- 更新 `app/` 和 `tests/` 内所有 first-party import。
- 更新 `.trellis/spec/backend/directory-structure.md` 中的目录说明。

## 不做什么

- 不改 FastAPI route URL。
- 不改 API response envelope、API fields、runtime status、language id、database schema。
- 不重写 runner、Agent、repository、grounding 的业务逻辑。
- 不整理 frontend。
- 不引入新依赖或新的框架。

## 验收标准

- `app/services` 和 `app/agents` 根目录的非 `__init__.py` 文件至少减少 70%。
- 新子包职责清楚，后续新增模块有明确归属。
- 所有旧 import 都迁移到新路径。
- runner、grounding、LLM、learning/review/onboarding/notes、本地用户数据相关测试继续通过。
- `ruff`、`mypy`、`task.py validate`、`git diff --check` 通过。

## 关键设计取舍

- 推荐直接迁移内部 import，不长期保留旧根路径 shim。
- 这样能真正减少根目录文件噪音，也避免后续出现两个入口。
- 如果选择保留 shim，短期风险更低，但目录会继续显得乱，而且新同事会不知道该 import 新路径还是旧路径。

## 执行顺序

1. 先用 `trellis-before-dev` 读取 backend spec。
2. 盘点当前 `app.services.*` 和 `app.agents.*` import。
3. 先移动 `grounding`、`runners` 这类高内聚模块。
4. 再移动 repositories、conversations、LLM、streaming。
5. 最后移动 `agents` 下 runtime、graphs、各 domain agent。
6. 每批移动后更新 import 并跑 focused tests。
7. 最后更新 backend directory spec，并跑完整质量门。

## 风险

- import 路径多，容易漏掉 tests 或 monkeypatch 路径。
- 子包拆分后可能暴露循环 import。
- `learning_conversation.py`、`agents/tools.py`、`test_llm_integration.py` 是高风险文件。
- 如果留下太多兼容 wrapper，会削弱这次整理的价值。

## 回滚点

- 每个领域子包按批移动，失败时只回滚当前批次。
- 如果出现循环 import，优先把共享 helper 放回 `agents/runtime` 或 `services/llm` 这类共享边界。
- 如果某个领域迁移风险过高，可以短期保留一个 wrapper，但 closeout 前必须记录理由和后续移除计划。

## Review Decision

- 已通过：直接迁移内部 import，并避免长期保留旧根路径 shim。
- 临时 wrapper 只能作为某个失败批次的短期脚手架使用，closeout 前必须删除；如果确实删不掉，需要写明具体 blocker。
