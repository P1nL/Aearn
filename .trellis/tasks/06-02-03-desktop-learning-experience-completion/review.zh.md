# 03 桌面学习体验补全 Review

## 你需要审核的结论

这个子任务只补齐桌面端“看得见的学习闭环”，不实现新的 runner、RAG、环境检测、数据导出/删除或自适应题目生成。

## 目标

让本地桌面端用户能从学习路线进入当前学习，完成概念对话、练习、运行/提交、复习、笔记和设置查看，不再遇到原型态死路或误导性能力展示。

## 范围

- 建档路线：只有最新路线卡能开始学习，确认计划有 loading/error 反馈。
- Dashboard/恢复：显示当前学习、今日复习、恢复入口和下一步动作。
- 学习页：概念优先会话、生成式练习卡、运行/提交/提示/错因解释/解释检查状态更清楚。
- 复习页：空态、加载、热身、热身修正、变体练习、`review_ai_patch`、提交结果和失败状态更清楚。
- 笔记：保存失败时保留本地编辑内容，并提供重试。
- 设置：七个分类完整展示，但不提前开放后续子任务负责的能力。

## 不做

- 不做 TypeScript/Go/C#/SQL/Java/C++ 新执行能力。
- 不做 official docs grounding 或 citation UI。
- 不做 environment doctor 和安装指导。
- 不做本地数据 export/delete/reset。
- 不做完整 UI 重设计或桌面安装包。

## 关键取舍

- 优先修真实闭环状态和边界文案，不重做视觉。
- 前端只展示后端事实，不本地计算评分、FSRS、复习完成态或 runner 结论。
- 后续能力只显示为“未开放/后续支持”，避免误导用户当前可执行。

## 验收

- `pnpm --dir .\aearn desktop:check` 通过。
- 受影响后端 API 测试通过。
- 学习练习能明确展示 preview/run、visible tests、submit、stale、unsupported、retry、hint、explain-error、check-explanation。
- 复习页不会在提交成功前暗示 FSRS 已更新。
- 笔记保存失败不丢本地草稿。
- 设置页不出现修改评分规则、FSRS、Attempt 事实记录、runner 安装或数据删除的入口。

## 实施顺序

1. 先对照现有规格和代码做桌面闭环审计。
2. 只 patch 最小必要桌面文件。
3. 如 API guard 与真实 payload 不一致，再做最小契约修复。
4. 运行桌面 build/type check 和相关后端测试。
5. 归档 `03` 后继续下一个子任务 `04-language-grounding-productization`。
