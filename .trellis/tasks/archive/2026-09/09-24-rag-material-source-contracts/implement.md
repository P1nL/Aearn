# A实施清单与验证顺序

> 最终交付：2026-09-24，步骤1–8的实现、复核、短spec及本地提交/归档已完成；代码提交1bbf364。没有真实搜索/DB/生产启用，B1未开始。下文“待提交”保留为实施时记录。

> 2026-09-24：当前会话绑定已修复，A处于in_progress。开始按下列顺序实现与验证；不再重复要求同范围批准，不新增真实搜索，不自动提交或push。

用户批准已记录在research/user-approval.md。A实现、独立检查和main复验完成；准确命令与验收见research/implementation-verification.md。当前保留未提交工作树，不自动归档或进入B。

## 依赖

- 父phase-ii-prd/design/implement v2和source-selection-extension已审阅。
- 阶段I01/02/03/04/06已提交归档；child05仅供计划模型数据一致性参考，不要求A写公开计划接口。
- 题库P0/P1/P3尚未完成，因此A只冻结跨owner合同；不假装全局身份/预算服务已存在。

## 实施顺序（进入执行阶段后）

1. 复核Git dirty ownership和相邻spec。当前工作树干净，不制造空checkpoint提交；如并行改动出现，先分类保护。
2. 以一个trellis-implement GPT-6-Sol窄写集完成纯合同和服务端/模型输入分层，避免共享文件并行冲突。
3. 加入deterministic策略判断和只读resolver port；默认拒绝缺失真实authority，无实际网络/DB依赖。
4. core/config.py最小加入四个false开关；无worker/router/entrypoint接线。
5. 覆盖AC1–AC9离线测试，检查旧fixture内容摘要、public mapping和现有检索边界不变。
6. 独立trellis-check GPT-6-Sol审查并限定修复；main复跑相关测试、全Ruff/Mypy/lock和diff。
7. 更新短spec/索引及任务验收证据。实际代码完成前不向现行spec写已实现承诺。
8. 主代理出具精确提交清单，按用户批准窄提交、归档；不自动开始B或发布新source。

## 预计验证

API子目录，PYTHON_DOTENV_DISABLED=1、LLM_TYPE=disabled、CODEX_RUNTIME_ENABLED=false及非业务DATABASE_URL：

```text
uv run pytest -q tests/grounding/test_rag_material_source_contracts.py tests/grounding/test_rag_source_access_policy.py tests/grounding/test_rag_source_usage_policy.py tests/grounding/test_rag_autonomous_boundary.py
uv run pytest -q tests/grounding/test_grounding_subjects.py tests/grounding/test_grounding_fixtures_v2.py tests/grounding/test_grounding_corpus_operator_boundary.py tests/grounding/test_grounding_retrieval_boundary.py
uv run ruff check app tests
uv run mypy app
uv lock --check
git diff --check
```

测试文件名为候选，以实际生成文件调整，不能把不存在路径或skip当通过。A不需要bootstrap真实PG；后续如发现必须持久化才能验的内容，归B，不偷偷扩scope。

## 真实来源核对

2026-09-24用户最新决定：取消模型原生联网接力；Tavily耗尽后仅使用已有知识库教材补足剩余缺口。B1/D验证额度耗尽路径零新增搜索、检索绑定已审核/适用/用途获准材料、材料已就绪且课程必需前置已满足的单元继续教学、本单元有教材但前置缺失不得越过依赖、剩余缺口如实保留。B1/C/D/E的空库/seed-only/错版本/撤权/错用途、额度错误分类及关闭态验证详见research/final-fallback-decision.md最小验收矩阵；A只验证离线合同fail-closed与用途/版本拒绝，不替代真实路由、覆盖和账本验收；无合格材料不生成虚假来源或完整标记。research/native-search-readiness.md作为历史调查保留，不再构成待选提供方或实现依赖。

Tavily后续接入采用research/tavily-budget-contract.md的预算要求。先完成B1持久化预算及异常测试，再接真实搜索；研究首轮16条包含已完成的1条，不能因会话重启或账户快照延迟重置预算。本轮只更新规划，不新增真实请求。

main拥有用户授权的小规模公开搜索/读取；只记录来源位置、可见版本、访问/正文可用情况、许可线索及候选用途，不下载整仓/整站/教材合集，不登录、不运行仓库脚本。网页工具返回不伪装成本仓库fetcher的HTTP/egress/provenance证明。
