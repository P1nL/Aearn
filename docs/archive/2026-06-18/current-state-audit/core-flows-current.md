# 当前核心流程（历史快照）

> **历史快照，非当前 source of truth。** 本文件生成于 2026-06-18，记录已移除的
> onboarding / learning-session / top-level review / notes runtime；目录名中的 `current` 不代表
> 2026-08-12 的 active runtime。当前事实请读取
> [`../../../README.md`](../../../README.md)、
> [`../../../architecture/tutor-harness-runtime.md`](../../../architecture/tutor-harness-runtime.md)、
> [`../../../architecture/api-contract.md`](../../../architecture/api-contract.md) 和
> [`../../../architecture/database-schema.md`](../../../architecture/database-schema.md)。不得据此恢复
> `/api/reviews`、`review_states` 或旧 Desktop 页面。

生成日期：2026-06-18

## Flow map

| 流程 | 当前状态 | 主要页面 | 主要 API | 核心持久化 |
|---|---|---|---|---|
| Cold start / bootstrap | Implemented | `App.tsx`、`useAppStore.ts` | `/health`、`/api/language-courses`、users/plans/dashboard/resume | `localStorage["aearn.bootstrap"]` |
| Onboarding | Implemented | `OnboardingPage.tsx`、`LearningRouteCard.tsx` | `/api/onboarding/messages`、`/api/onboarding/{conversation_id}/confirm_plan`、`/api/plans` | onboarding conversations/messages、plans/modules/kps/review_states |
| Dynamic plan generation | Partially implemented | `PlanDraftPanel.tsx` | `/api/plans/generate` | no direct plan write until confirm |
| Learning workspace | Implemented | `LearningWorkspacePage.tsx`、`DocumentationPanel.tsx`、`ExerciseWorkbench.tsx` | `/api/learning-sessions/*` | learning_sessions、learning_messages、attempts、review_states |
| Review | Implemented | `ReviewPage.tsx`、review generative cards | `/api/reviews/*` | review_states、review_seed_banks、review_logs、attempts、review_messages |
| Notes | Implemented | `NotesPage.tsx`、`NoteDrawer.tsx` | `/api/notes`、`/api/notes/{id}/agent-draft` | notes |
| Settings / local data | Implemented | `SettingsPage.tsx` | users preferences/export/reset/delete/data-summary、environment doctor | users、learner_profiles、local data summaries |

## 1. Cold start, dashboard, resume

| Step | Frontend | Backend | Tests |
|---|---|---|---|
| 无 bootstrap | `useAppStore.initializeApp()` 调 `/health` 和 `/api/language-courses`，进入 onboarding | `routes/health.py`、`routes/courses.py` | `test_health.py`、`test_onboarding_m2.py` |
| 有 bootstrap | 读取 `localStorage["aearn.bootstrap"]` 后验证 user/plan | `GET /api/users/{user_id}`、`GET /api/plans/{plan_id}` | `test_dashboard_resume_m6.py` |
| 决定入口 | dashboard + resume 决定继续学习或复习提示，不信任 localStorage alone | `GET /api/dashboard`、`GET /api/learning-sessions/resume` | `test_dashboard_resume_m6.py` |
| 无效 bootstrap | frontend 清理本地 bootstrap，回到 onboarding | user/plan 404 | `test_local_user_data_boundary.py` |

面试表达：Aearn 把 localStorage 当作“缓存指针”，不是 source of truth。真正恢复路径来自 backend user/plan/dashboard/resume。

## 2. Onboarding chat to confirmed plan

| Step | Frontend | Backend | Persistence |
|---|---|---|---|
| 用户输入目标 | `OnboardingPage` 通过 `buildOnboardingMessageSSEUrl()` 发 POST SSE | `POST /api/onboarding/messages` | `onboarding_conversations`、`onboarding_messages` |
| Slot extraction | SSE 返回 `agent_message`、可能返回 `tool_call` | `onboarding_conversation.py`、`onboarding_slot_extractor.py` | extracted slots in conversation state |
| 生成路线卡 | `LearningRouteCard` 渲染 `show_learning_route` tool args，旧卡禁用 | `learning_route_args_from_plan_draft()`、`stash_plan_draft()` | stashed plan draft |
| 确认计划 | 最新卡片点击 `开始学习` | `POST /api/onboarding/{conversation_id}/confirm_plan` 或 `POST /api/plans` | `learning_plans`、`plan_modules`、`knowledge_points`、`review_states` |
| 进入学习 | App store 保存 `userId` / `planId` 到 `aearn.bootstrap` | plan detail response | active plan context |

当前边界：

| 项 | 判断 |
|---|---|
| TypeScript / SQL / Go / C# | 公开路线语言 |
| C++ / Rust | 非公开路线，应返回 unsupported / not supported guidance |
| Dynamic route | 依赖 LLM/provider/config/source coverage；无配置时不要说“必定动态生成” |
| Latest-card-wins | 前端只允许最新路线卡开始学习 |

## 3. Learning workspace

| Step | Frontend | Backend | Persistence |
|---|---|---|---|
| 开始知识点 | sidebar 或 dashboard 触发 `startLearningSession()` | `POST /api/learning-sessions/start` | `learning_sessions`，stage 初始可为 `documentation_reading` |
| 右侧文档 | `DocumentationPanel` 调 `fetchKnowledgePointDocumentation()` | `GET /api/learning-sessions/knowledge-points/{id}/documentation` | best-effort Redis cache、grounding/lesson sources |
| 触发概念检查 | `ConceptCheckTrigger` 调 `triggerConceptCheck()` | `POST /api/learning-sessions/{session_id}/trigger-concept-check` | stage 更新为 `concept_check` |
| 对话 | assistant-ui thread + `useSSE` | `POST /api/learning-sessions/{session_id}/messages` | `learning_messages` |
| 生成/恢复练习 | `ExerciseWorkbench` 渲染 exercise card 和本地编辑状态 | session response / repository materialization | `exercises`、latest attempt state |

关键前端边界：

| 边界 | 当前实现 |
|---|---|
| Composer | 只有 active learning session 时可发送，POST SSE，不用 `EventSource` |
| 文档引用 | 通过 assistant-ui composer prefill，不直接 DOM 改 textarea |
| 练习卡 | 在 conversation flow 内，不是旧固定 workbench 假数据 |
| Stale run | 代码或 blanks 改动后旧 run 结果不能直接 masquerade as current |

## 4. Run, hint, explain, check, submit

| Action | Frontend helper | Backend route | Backend owner |
|---|---|---|---|
| Preview / visible tests | `runLearningExercise()` | `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run` | `run_learning_session_exercise()` |
| Hint | `requestLearningHint()` | `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/hint` | `request_learning_hint()` |
| Explain error | `explainLearningError()` | `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error` | `explain_learning_attempt_error()` |
| Check explanation | `checkLearningExplanation()` | `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/check-explanation` | `check_learning_attempt_explanation()` |
| Submit | `submitLearningExercise()` | `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit` | `submit_learning_session_exercise()` |

Submit 的事实链：

| Fact | Owner |
|---|---|
| code hash / filled blanks identity | backend repository |
| runtime result | runner registry + selected runner |
| score breakdown / fsrs_rating | `app/services/exercises/evaluation.py` |
| ReviewState update | `review_scheduler.apply_attempt_review_update()` |
| UI label | frontend label helper，只展示 backend response |

## 5. Review flow

| Step | Frontend | Backend | Persistence |
|---|---|---|---|
| 拉取今日复习 | `ReviewPage` active 时调用 `fetchTodayReviews()` | `GET /api/reviews/today` | reads `review_states` |
| 开始复习 | `startReviewSession()` | `POST /api/reviews/start` | `learning_sessions(session_type='review')` |
| 确保候选池 | frontend 不参与 | `ensure_ready_review_seed_bank()` | `review_seed_banks` |
| Warmup | `submitReviewWarmupResult()` | `POST /api/reviews/{session_id}/warmup-result` | session review stage state, review_messages |
| Run review exercise | 复用 `runLearningExercise()` | learning run endpoint | `Attempt(run)` |
| Submit review | `submitReviewExerciseResult()` | `POST /api/reviews/{session_id}/exercise-result` | `Attempt(review_submit)`、batch state |
| Finalize | frontend 渲染 `due_at` / `forget_risk` | `apply_review_batch_update()` | `ReviewState`、`ReviewLog` |

重要边界：

| 边界 | 当前判断 |
|---|---|
| Warmup | 不写 Attempt，不更新 ReviewState |
| Intermediate review submit | 写 review submit Attempt 和 session state，不立刻污染长期 FSRS |
| Final review submit | 聚合 batch final rating 后才更新 ReviewState/ReviewLog |
| Adaptive supplement | 无法覆盖弱点时返回 recoverable error，不合成低质 fallback 问题 |
| `review_ai_patch` | first-class exercise type，有专用 scoring breakdown |

## 6. Notes

| Step | Frontend | Backend | Persistence |
|---|---|---|---|
| Note drawer | `NoteDrawer` 可从学习/复习上下文打开 | `GET /api/notes` | `notes` |
| Create/update | `useNotesStore` 调 `createNote()` / `updateNote()` | `POST /api/notes`、`PATCH /api/notes/{note_id}` | `notes` |
| Agent draft | `requestNoteAgentDraft()` | `POST /api/notes/{note_id}/agent-draft` | note draft response / update path |
| Notes page | `NotesPage` 展示和筛选 | `GET /api/notes?user_id=...` | `notes` |

## 7. Settings and local data

| 功能 | API | 当前边界 |
|---|---|---|
| Preferences | `PATCH /api/users/{user_id}/preferences` | 用户偏好，不改变 scoring/FSRS internal rules |
| Data summary | `GET /api/users/{user_id}/data-summary` | 本地用户数据摘要 |
| Export | `GET /api/users/{user_id}/export` | learner-safe JSON，不导出 secrets/hidden tests/raw prompts |
| Reset | `POST /api/users/{user_id}/reset-data` | 清理用户学习数据 |
| Delete | `DELETE /api/users/{user_id}` | 删除本地用户 |
| Environment doctor | `GET /api/environment/doctor` | 检查工具链和能力边界，不把检测到 toolchain 误说成公开支持 |

## 8. 测试映射

| Flow | 主要测试 |
|---|---|
| Onboarding / plan | `test_onboarding_m2.py`、`test_plan_generator.py`、`test_plan_generation_agent.py`、`test_onboarding_graph.py` |
| Learning session | `test_learning_sessions_m3.py`、`test_learning_graph.py`、`test_graph_event_stream.py` |
| Review | `test_reviews_m4.py`、`test_review_graph.py` |
| Notes | `test_notes_m5.py` |
| Dashboard / resume | `test_dashboard_resume_m6.py` |
| Local data | `test_local_user_data_boundary.py` |
| Runners | `test_runner_registry.py`、`test_browser_preview_runner.py`、`test_sql_query_runner.py`、`test_node_typescript_runner.py`、`test_managed_compiled_runner.py` |
| Graph/runtime contract | `test_graph_runtime_contracts.py`、`test_sse_utils.py` |
| Grounding | `test_grounding_*` |
