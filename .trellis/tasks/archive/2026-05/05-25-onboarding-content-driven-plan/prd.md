# Content-driven onboarding plan generation

## Goal

让 AI 从对话上下文中真正"理解"用户想学什么，按内容（而非轮数）触发学习计划生成，并用 LLM 抽取的结构化信息生成真实的 PlanDraft —— 替换当前 `user_turns >= 4` 的硬阈值和 `build_deterministic_learning_route` 的固定 stub。

## Background

当前 onboarding 的 plan 触发路径有三个独立问题：

1. **触发与内容脱钩** (`onboarding_conversation.py:318-326`)
   `detect_plan_proposal` 仅检查 `user_turns >= 4`，跟用户说了什么完全无关。首轮就给出完整目标的用户要被硬聊 3 轮；连续敷衍的用户到第 4 轮也会硬触发。

2. **生成内容硬编码** (`onboarding_conversation.py:329-384`)
   `build_deterministic_learning_route` 永远返回同一个 stub：`language="javascript"`、模块固定为「基础语法 / 动手练习」。唯一从对话取的是 `goal_text = user_messages[0][:80]`，因此用户首条消息打 `hi` 就会得到 `goal_text="hi"` 的计划。

3. **卡片与确认计划不一致** (`OnboardingPage.tsx` `handleConfirmPlan`)
   前端 confirm 时不复用 SSE 推过来的 `learning_route_args`，而是用第一条用户消息当 `goal_text`、`courses[0]` 当语言，重新调 `/api/plans/generate` 生成另一份 PlanDraft 再 confirm。用户在卡片上看到的内容跟最终入库的计划是两份独立生成的产物。

LLM 配置已在 `aearn/.env` 接通（`LLM_TYPE=openai`、`OPENAI_BASE_URL=https://api.lattecode.net`、`OPENAI_MODEL=gpt-5.5`），具备做结构化抽取的能力。

## Requirements

### Backend: 结构化槽位抽取

- 在 onboarding agent 中加入结构化输出能力，每轮从对话历史中抽取以下槽位：
  - `language`: `"javascript" | "python" | "java" | "cpp" | "html_css" | null`
  - `target_level`: `"beginner" | "intermediate" | "advanced" | "beginner_to_intermediate" | null`
  - `goal_text`: 用户学习目标的自然语言概述（≥10 字）
  - `time_budget`: `{ minutes_per_day, days_per_week } | null`
  - `focus`: 重点方向自由文本（如 "Web 开发"、"算法竞赛"）| null
  - `plan_ready`: bool，AI 自己判断槽位是否齐全到可以提计划草案
- 抽取结果累积写入 `onboarding_conversations.extracted_context`（已存在 jsonb 列）
- 抽取应是**累积式**：本轮没补全的字段保留上一轮的值，不要每轮归零
- LLM 不可用时走 deterministic 降级：用关键词扫历史（语言名、"零基础/进阶"、数字+小时/分钟 等）填槽位，缺一个槽位都不触发

### Backend: 内容驱动触发

- `detect_plan_proposal` 改判 `extracted_context.plan_ready`（或所有必填槽位齐全）而非轮数
- 不再有硬上限；agent 槽位齐了就生成，没齐就继续追问
- agent system prompt 加入"按缺啥问啥"的指引，避免冗余追问

### Backend: 真实 PlanDraft 生成与暂存

- 触发时用抽取到的槽位（`language`、`target_level`、`goal_text`、`time_budget`）调 `plan_generator.build_plan_draft`，生成完整 PlanDraft
- 把 PlanDraft 序列化暂存到 `onboarding_conversations.extracted_context.plan_draft`
- SSE `show_learning_route` tool call 用这份真实 PlanDraft 投影出简化的 `LearningRouteArgs`（`plan_id` 用 `draft_id`，模块/知识点直接映射），与最终入库的 plan 内容**完全一致**

### Backend: 确认接口改造

- 在 `/api/plans` 路由下新增分支或新增 `POST /api/onboarding/{conversation_id}/confirm_plan`：
  - 入参只需 `onboarding_session_id`（+ 鉴权 user_id）
  - 后端从 `extracted_context.plan_draft` 取出暂存草稿，走 `confirm_plan` 入库
  - 不再二次 generate
- 兼容期：保留旧 `POST /api/plans` 完整 PlanDraft 入参（其他流程仍可能用）

### Frontend: 确认路径精简

- `handleConfirmPlan` 改成只传 `onboarding_session_id`，不再调 `generatePlanDraft`
- 卡片上展示的 `LearningRouteArgs` 与 confirm 后入库的 plan 一致
- "调整计划" 按钮触发时把"我想调整……"作为新一轮 user message 发给 agent，agent 在已有槽位基础上修改并重新生成（暂存的 plan_draft 被覆盖）

### 错误与边界

- LLM 抽取失败（解析不出结构化输出）→ 当前轮按"槽位未变化"处理，不阻断对话流
- 抽到的 `language` 不在课程目录里 → agent 主动澄清（"我们目前主要支持 Python/JavaScript/HTML+CSS，你倾向哪一个？"）
- `build_plan_draft` 抛错（`PlanDraftError`）→ SSE 推 `error` 事件，不发 `show_learning_route` tool call

## Acceptance Criteria

- [ ] 用户首轮消息已包含完整信息（如"我想学 Python Web 后端，零基础，每天 1 小时"）→ 第 1 轮就触发 `show_learning_route`
- [ ] 用户连续 5 轮敷衍回答 → 不触发，agent 继续追问缺失槽位
- [ ] `show_learning_route` 卡片的 `goal_text`、`language`、模块名均来自对话内容，不是固定 stub
- [ ] `extracted_context.plan_draft` 存有完整 PlanDraft；session resume 时能直接渲染
- [ ] 前端点"确认学习计划"只传 `onboarding_session_id`，后端不再二次 generate
- [ ] 卡片上看到的模块名/知识点 ≡ 入库后 `LearningPlan` 表里的内容
- [ ] LLM 不可用时降级到关键词槽位抽取，不会走旧的轮数硬阈值
- [ ] `pnpm --dir .\aearn desktop:check` 通过
- [ ] 浏览器烟囱测试：4 轮"Python / 零基础 / 每天 30 分钟 / Web 开发"流程产出 Python 相关的真实计划

## Out of Scope

- 修改 `plan_generator.build_plan_draft` 内部生成逻辑（继续复用现有的课程模板）
- 多语言/多课程混合学习计划
- 历史会话归档与跨设备同步
- assistant-ui generative UI 的其他卡片（在父任务 `05-25-assistant-ui-generative-ui` 范围内）

## Dependencies

- 父任务 `05-25-assistant-ui-generative-ui` Slice 1 已交付的 `tool_call` SSE 协议、`onboarding_messages.metadata` 持久化能力
- `aearn/.env` 已配置可用的 OpenAI 兼容 endpoint
