# Implementation Plan: RAG Subject and Capability Taxonomy

## 2026-09-23 执行记录

- 用户已明确要求使用 GPT-6-Sol 子代理执行，并要求先提交工作树；本轮复用现有任务，不新建联合协调任务。
- 原工作树已原状提交为 `910d163`（`chore: checkpoint source artifacts and tutor acceptance work`），44 个实际内容变更文件；提交后工作树干净，未推送。此前状态的 50 个路径包含 Git 暂存规范化后无实际内容差异的文件；未强制加入被忽略的本地任务/运行材料。
- checkpoint 仅保存既有工作，不声明旧功能全部验收通过；既有 `test_source_inspector.py` 的 EOF 空行告警保留。checkpoint 后补跑 prompt contracts 6 passed、fake-client grounding fetcher 6 passed、`uv lock --check` 通过。
- 当前 child 已从 planning 切换到 in_progress；执行与检查子代理均使用 GPT-6-Sol，默认 high，必要独立检查 xhigh。旧文件中的 GPT-5.6-Sol 约定由本轮明确用户指令替代。
- 首个实现写集仅为两个 Subject 模块与其定向测试。真实 provider、数据库、worker、浏览器、语料激活和正式供题均未启动，不把离线证据计入 B1 真实验收。
- 用户当前提交授权用于执行前 checkpoint；本轮后续新增实现不自动再次提交或推送，不因代码检查通过提前归档父任务。


## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child阶段I仍定义operator_locked/fixture-only等原合同。后续自主治理只能消费预登记source/Subject/version授权与release状态，不得通过题库扩域或自动公开生态；若增加v2版本策略必须新合同，不改旧值含义。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

1. Load backend specs and inspect adjacent language/grounding registries and tests.
2. Add strict Subject and capability contracts.
3. Add the four-route/six-ecosystem immutable registry and validation helpers.
4. Add capability composition helpers without changing existing public mapping.
5. Add unit tests for identity, aliases, parent graph, facets, runtime compatibility, release-state admission and HTML/CSS compatibility.
6. Run focused pytest, Ruff, Mypy and existing language/grounding registry regressions.
7. Run Trellis check, commit/archive this child, then stop.

## Expected Write Scope

- `aearn/services/api/app/services/grounding/subject_contracts.py`
- `aearn/services/api/app/services/grounding/subject_registry.py`
- focused tests under `aearn/services/api/tests/grounding/`
- minimal spec/docs updates only if the new contract must be recorded immediately

## Verification

```powershell
uv --directory .\aearn\services\api run pytest -q tests/grounding/test_grounding_subjects.py tests/grounding/test_grounding_sources.py tests/runners/test_language_capabilities.py
uv --directory .\aearn\services\api run ruff check app/services/grounding tests/grounding/test_grounding_subjects.py
uv --directory .\aearn\services\api run mypy app/services/grounding/subject_contracts.py app/services/grounding/subject_registry.py
```


## 2026-09-23 首个 child 工程检查结果

- 实现：新增 `subject_contracts.py`、`subject_registry.py`、`test_grounding_subjects.py`；主代理在既有 backend integration QA spec 补充边界。既有公开课程/语言映射文件未修改。
- GPT-6-Sol high 实现、GPT-6-Sol xhigh 独立检查；复查修复严格空白校验、release/component 越权、shadow 误报执行能力、fixture 来源覆盖误报，以及畸形 registry 图遍历崩溃。
- 主代理复验发现畸形 parent 列表仍在第二遍父图检查崩溃，交回同一检查代理修复。新增三个回归（修复前 3 failed，修复后 3 passed）；后续图遍历只使用通过结构检查的条目。
- 最终主代理从 `aearn/services/api` 执行：
  - `uv run pytest -q tests/grounding/test_grounding_subjects.py tests/grounding/test_grounding_sources.py tests/runners/test_language_capabilities.py tests/grounding/test_grounding_fetcher.py tests/integration/test_prompt_contracts.py`：**48 passed**。
  - `uv run ruff check app/services/grounding/subject_contracts.py app/services/grounding/subject_registry.py tests/grounding/test_grounding_subjects.py`：通过。
  - `uv run mypy app/services/grounding/subject_contracts.py app/services/grounding/subject_registry.py`：通过（2 source files）。
  - `uv lock --check`：通过。
  - tracked diff whitespace 检查无告警；3 个未跟踪新增文件另行检查 trailing whitespace、EOF 空行、末尾换行均通过。`git diff --no-index --check` 的差异退出码不记为测试失败。
- child PRD 六项工程 AC 已据上述证据勾选。代码尚未提交，任务保留 in_progress，不归档；唯一新提交仍是执行前 checkpoint `910d163`。
- 联合 W0 审查见 `research/joint-contract-review-20260923.md`。目标到 Subject/version/facets 的共同映射与 pending/waiting_result 区分仍需在后续消费者接线前冻结，不将 W0 整体标完成。
- 后续 child02 版本化语料权威、其余 RAG children、自主来源治理、题库/沙盘、推进与收尾未在本轮实现。没有真实来源/题目发布/Artifact/Gate/完整小节通过证据；不能将本 child 的离线合同测试计入 B1 真实验收。

## 2026-09-23 提交与交接

用户明确同意提交上一轮4文件后继续。已提交 `3d54036`（feat: add guarded RAG subject capability taxonomy），未推送。任务是本地非PR交付，归档使用 no-commit 与 skip-branch-validation，不创建PR或额外Git提交。下一child的已提交Subject前置已满足。
