# 新会话实施交接

## 状态

- 用户已于 `2026-08-19` 明确批准最终规划。
- 本任务仍为 `planning`，当前会话没有运行 `task.py start`，也没有修改产品代码。
- 下一会话必须启动本任务：`08-19-codex-thread-context-raw-runtime-stream`。
- 当前 session fallback 仍可能错误指向 stale 的 `08-13-codex-like-tutor-conversation-experience`；不要启动、恢复或改写该旧任务。
- 不要重建任务，不要创建新的父任务或 child。

## 精确启动命令

在 PowerShell 中：

```powershell
Set-Location E:\codee\Aearn
python .\.trellis\scripts\task.py start 08-19-codex-thread-context-raw-runtime-stream
python .\.trellis\scripts\task.py current --source
```

第二条命令必须显示：

```text
Current task: .trellis/tasks/08-19-codex-thread-context-raw-runtime-stream
```

如果仍显示 `08-13`，不要实施，先修正当前 session 的 Trellis pointer。

## 下一会话提示词

```text
在 E:\codee\Aearn 实施已批准任务：
.trellis/tasks/08-19-codex-thread-context-raw-runtime-stream

先执行：
python ./.trellis/scripts/task.py start 08-19-codex-thread-context-raw-runtime-stream
python ./.trellis/scripts/task.py current --source

边界：
- 不要启动 stale 的 08-13-codex-like-tutor-conversation-experience。
- 不要重建任务、不要重做规划、不要创建新的父任务或 child。
- 当前是 Codex inline 模式，不派发 implement/check sub-agent。
- 先加载 trellis-before-dev，再依次读取 prd.md、design.md、implement.md、research/codex-runtime-compaction.md。
- 按 implement.md 顺序完成全部 P0/P1；修改后加载 trellis-check 并完成全量验证。
- 不调用真实 provider，除非我再次明确批准。
- 不提交、不 push、不部署。
- 不覆盖用户已有的 .trellis/tasks/.obsidian 修改。

关键已批准决策：
1. 一个 TutorConversation 对应一个持久 Codex App Server thread；每个 fresh TutorRun 对应该 thread 内的新 turn。
2. PRD 中 Codex 指本地受控 `codex app-server --stdio --strict-config` sidecar，不是模型；实际模型仍是 deepseek-v4-flash。
3. 当前 aearn_deepseek 使用 Codex local compaction；local 仍通过普通 Responses 调用 DeepSeek 生成摘要，不启用未经验证的 remote compaction。
4. exact context capability 为 1_000_000 / 384_000 / 616_000；Codex auto-compact limit 从同一 source of truth 派生。
5. raw reasoning 与 raw final-answer delta 按 item/phase 分离；commentary 不显示、不混入。
6. raw reasoning 写入 owner-scoped PostgreSQL 私有 runtime projection，支持重连、刷新和历史；completed item 是终态 authority。
7. 前端同一 Tutor entry 显示小写 `think`、左边框 reasoning、下方直接流式 answer；当前展开、历史折叠、无 reasoning 时终态无空 Think。
8. PostgreSQL planning facts/typed request/LearningPlan/Queue/权限继续是 Aearn authority；Codex history 与 compaction 不能替代。

已批准工件：
- .trellis/tasks/08-19-codex-thread-context-raw-runtime-stream/prd.md
- .trellis/tasks/08-19-codex-thread-context-raw-runtime-stream/design.md
- .trellis/tasks/08-19-codex-thread-context-raw-runtime-stream/implement.md
- .trellis/tasks/08-19-codex-thread-context-raw-runtime-stream/research/codex-runtime-compaction.md
```

## 已知用户修改

以下文件不是本任务修改范围，不得覆盖或提交：

- `.trellis/tasks/.obsidian/plugins/translate/data.json`
- `.trellis/tasks/.obsidian/workspace.json`
