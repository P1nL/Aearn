# Adaptive exercise template system 审核稿

## 目标

把当前静态 `_exercise_template(...)` 和 review seed 变体升级成可产品化的 adaptive exercise template system：先从 canonical templates 生成候选题，再通过对应 runner 验证，验证通过才给 learner 使用；失败则回退到稳定模板。

## 范围

- 建立 canonical template catalog，包含 `template_id`、`template_version`、language/runtime、visible/hidden tests、fallback payload。
- 初版直接走 model-assisted candidate：模型根据 canonical template envelope 和 bounded learner context 生成候选变体。
- 输入只来自 knowledge point、weak points、recent visible attempt facts、runtime capability 等安全上下文。
- 每个 candidate 必须先通过 runner validation。
- 缓存已验证 variants，并按 user/knowledge point/template/version/runner scope 复用。
- reset/export/delete 要覆盖 user-specific variant cache。

## 不做

- 不做完全开放式无模板生成。
- 不把未验证的 model-generated exercise 给 learner。
- 不做云端共享 variant cache。
- 不做模板 authoring UI。
- 不做 Rust/C++ L3 execution templates。

## 关键设计取舍

- 初版直接使用 model-assisted candidate，提高变体个性化和题目多样性。
- deterministic parameterized generation 不作为主路径，只保留为 provider failure、invalid model output 和测试 fixture 的 fallback。
- 关键安全边界不变：模型生成的题不能直接给 learner，必须先通过同一个 runner validation gate。
- 代价是实现复杂度更高，需要额外覆盖 model payload invalid、provider failure、unsafe content、validation failure 等回退测试。

## 验收标准

- canonical templates 有稳定 id/version。
- model-assisted candidate variants 带 generator/model/template/version metadata。
- Python 和至少一个 browser/Node family 的 candidate 能通过 runner validation。
- SQL adaptive variants 依赖 `06-02-sql-query-runner`，SQL runner 未完成时保持 disabled/fallback。
- invalid model output、provider failure、unsafe content、runner validation failure 都不会打断 learning/review flow，会回退到 stable template 或 deterministic fallback。
- cache hit/miss、version invalidation、user isolation、reset/delete/export 都有测试或明确代码行为。
- hidden tests、solution_reference、raw prompts、provider payloads、validation internals 不泄露。

## 执行顺序

1. 先写 focused failing tests。
2. 加 canonical template catalog。
3. 加 model-assisted adaptive exercise service。
4. 加 variant cache schema。
5. 接入 `exercise_repository.py` 和 review seed flow。
6. 更新 local user data boundary 的 reset/export/delete。
7. 跑 focused tests、`ruff`、`mypy`、`task.py validate`、`git diff --check`。

## 风险

- 如果 validation gate 不严格，生成坏题会直接进入学习流。
- 如果 cache 不按 user/version 隔离，会破坏本地用户数据边界。
- model-assisted 主路径增加 provider failure 和 invalid JSON/schema 风险。

## 回滚点

- 关闭 model-assisted generation，回到 deterministic fallback 或现有 `_exercise_template(...)`。
- 忽略或 archive variant cache。
- 保留 canonical fallback templates。
- SQL variants 在 SQL runner 完成前保持 disabled。

## 待确认

- 已按你的方向调整：初版 model-assisted candidate 优先；deterministic 只做 fallback/test fixture。实现前仍需确认 review 后再 `task.py start`。
