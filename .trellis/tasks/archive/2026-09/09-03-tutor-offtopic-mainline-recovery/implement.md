# 实施计划：用户聊天方向偏移后的主线恢复

## 1. 实施前保护

- [ ] 重新读取当前 task、branch 和 `git status --short`，记录本任务开始前的非任务修改。
- [ ] 只认领本任务的 provider policy、Codex instructions、新 Skill 版本、测试、规格和任务文件；不清理或重置并行修改。
- [ ] 读取 context manifests 与 `research/current-behavior.md`，确认 blocking Artifact branch 仍是唯一 branch authority。

## 2. 建立共享方向恢复合同

- [ ] 更新 `provider_request.py` 的 `TUTOR_TEACHING_POLICY`，定义 continue_mainline、answer_and_refocus、clarify_direction、confirmed_switch 四类语义。
- [ ] 明确 latest input/server authority 高于旧消息、摘要和 persistent-thread 联想。
- [ ] 保证 replacement prompt 复用相同规则；禁止关键词硬编码和多问题分叉。

## 3. 发布 LearningPlan Skill 新版本

- [ ] 从 `tutor.learning-plan-draft/1.0.2` 创建不可变新版本 `1.0.3`，完整保留现有 planning/language/draft 合同。
- [ ] 加入通用聊天方向偏移规则和多主题正反例，不将“厨师”作为特殊规则。
- [ ] evals 覆盖非编程岔题、编程内跨主题、疑似换目标、明确换目标、同主题延伸和普通 semantic-language 非回归。
- [ ] 计算 raw-byte SHA-256，更新 manifest，验证 LF 和末尾换行。
- [ ] 更新 `plan_policy.py` 的当前 LearningPlan Skill 选择；旧 `1.0.2` 内容与 hash 保持不变。

## 4. 发布 LessonTeaching Skill 新版本

- [ ] 从 `tutor.lesson-teaching/1.2.0` 创建不可变新版本 `1.2.1`，保留 v3 teaching-step/interaction/Artifact 合同。
- [ ] 加入临时岔题回答后恢复 current objective/focus、方向不明只问一个 composer 问题、明确切换不得伪造 authority 的规则。
- [ ] evals 增加 SQL→CSS、Python 变量→网络概念、明确切换和相关延伸等聊天方向偏移场景。
- [ ] 计算 raw-byte SHA-256，更新 manifest，验证 LF 和旧版本不可变。
- [ ] 更新 `plan_policy.py` 的当前 Teaching Skill 选择，并修正测试中所有“当前版本”断言；历史版本测试继续固定旧 hash。

## 5. 对齐 Codex plan-drafting

- [ ] 更新 `codex_dispatcher.py` `_BASE_INSTRUCTIONS`：latest learner input 和 server facts 高于 persistent thread。
- [ ] 写入与 Harness 相同的 continue / answer-refocus / clarify / confirmed-switch 语义。
- [ ] 保持 `aearn_planning_context_read`、semantic hint、server exact question、typed request 和 capability authority 不变。

## 6. 回归测试矩阵

- [ ] 更新 `test_tutor_provider_gateway.py`，验证首次和 replacement policy 均包含通用方向恢复合同。
- [ ] 更新 `test_tutor_skill_catalog.py`，验证两个新 Skill 版本、旧 hash 不变、新 hash 与 LF 正确。
- [ ] 更新 LearningPlan/Codex tests，覆盖 persistent-thread 旧方向不能覆盖最新输入。
- [ ] 更新 teaching context/action-loop tests，覆盖用户聊天方向偏移后的 answer/refocus、单问题澄清和明确切换边界。
- [ ] 保留并运行 `test_tutor_branch_continuation.py` 的既有 answer/refocus、offer/confirm switch 非回归。
- [ ] 参数化场景至少覆盖：
  - [ ] 非编程岔题；
  - [ ] 编程领域内跨主题岔题；
  - [ ] 局部概念岔题；
  - [ ] 疑似新主题素材；
  - [ ] 明确的同主题延伸；
  - [ ] 明确切换并拒绝旧方向；
  - [ ] 临时提问后恢复原主线。
- [ ] 断言不得依赖“厨师”等单一关键词，也不得把所有新主题都强制拉回旧主线。

## 7. 建立 Codex 有界方向决策与成功标志

- [ ] 撤销所有仅用于隐藏 reasoning 的 Runtime projection、conversation query/SSE、Desktop contract/parser/reducer/renderer、测试、文档和规格改动，恢复 reasoning `think` 的修改前行为。
- [ ] 将 Codex planning direction 输入收敛为一个 closed `direction_action`，覆盖 `continue_mainline / answer_and_refocus / clarify_direction / confirmed_switch`，替代“缺少布尔值即默认主线”的隐式语义。
- [ ] Registry 只在 tool result 合法时写入当前 Turn 的 accepted action marker；拒绝冲突、多次变更、无 context 直接决策和 draft 前缺失 marker。
- [ ] 精简 `_BASE_INSTRUCTIONS`：首次 context read 后立即提交一个 closed action，不在 reasoning 中递归讨论，也不在 action accepted 后重复分类。
- [ ] dispatcher 对四类 action 使用显式分支；无 accepted marker 时忽略模型 final answer，创建一个 deterministic server-owned direction clarification。
- [ ] `clarify_direction` 始终使用明确的 server prompt，不再以“任意只有一个问号的 final answer”为合法纠偏；`answer_and_refocus` 才允许保留以 exact question 结束的模型前置回答。
- [ ] 保留 `confirmed_switch` 的 append-only fact reopen、language semantic shortlist 和既有 typed request authority，不新增公开 API/DB enum。
- [ ] 增加工具、dispatcher 与 live Runtime regression：覆盖四类 action、重复/冲突 action、缺 marker、截图类模糊偏航、正常同主题延伸和 reasoning 仍进入 `think` 投影。

## 8. 文档与规格

- [ ] 在最邻近的 backend Tutor/teaching 规格中记录通用方向偏移合同、closed action marker 和缺 marker fail-closed，避免分别维护冲突定义。
- [ ] 更新 `docs/architecture/tutor-harness-runtime.md`、`docs/product/user-flows.md` 和 `docs/qa/acceptance-test-plan.md` 的用户聊天方向偏移与测试映射。
- [ ] 不修改受保护原型或 Desktop UI，除非实现证据显示公开合同必须变化并先返回规划评审。

## 9. 验证命令

```powershell
uv --directory .\aearn\services\api run python -m pytest `
  tests/tutor/test_tutor_skill_catalog.py `
  tests/tutor/test_tutor_provider_gateway.py `
  tests/codex_sidecar/test_codex_plan_drafting_cutover.py `
  tests/tutor/test_tutor_teaching_context.py `
  tests/tutor/test_tutor_teaching_action_loop.py `
  tests/tutor/test_tutor_branch_continuation.py -q

uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .trellis/tasks/09-03-tutor-offtopic-mainline-recovery
git diff --check
```

若公共 Harness/Skill 合同影响范围超出 focused tests，则按 backend quality gate 串行运行完整 API pytest；bootstrap-sensitive 测试不得并行。

## 10. 检查、提交和回滚

- [ ] 派发 Trellis check，重点检查：是否仍是通用语义、是否误伤正常延伸、closed marker 是否真正约束终态、reasoning 展示是否已恢复、旧 Skill 是否不可变、是否复制了 branch authority。
- [ ] 修复所有任务相关 P0/P1 并重跑失败验证。
- [ ] 对照初始 dirty inventory，只暂存本任务文件，不纳入其他 Trellis 更新或并行修改。
- [ ] 提交前重跑 focused tests、Trellis validate 和 `git diff --check`。
- [ ] 回滚仅撤销新 Skill 当前选择、共享指令、测试和文档；保留所有旧 Skill 版本。
