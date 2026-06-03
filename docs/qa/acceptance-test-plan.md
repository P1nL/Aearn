# Aearn 测试与验收计划

日期：2026-05-13  
状态：Draft V1.1  
适用范围：Aearn 第一版稳定基线、post-MVP / v1.1 增强、API 契约、Agent 输出质量、FSRS 调度、代码补全验证和前端手工 QA

## 目标

本计划定义产品达到可实施验收的测试口径。验收必须覆盖确定性行为和 LLM 输出质量，但二者分开评估：确定性测试检查 API、状态、评分规则、FSRS、运行反馈是否稳定；LLM 输出质量测试检查 Agent 是否按证据生成结构化、具体、可执行的解释和反馈。

不允许把“模型看起来回答不错”作为唯一通过标准。所有 LLM 相关验收至少要同时满足结构校验、证据一致性校验和人工或半自动 rubric 评分。

## 优先级定义

| 优先级 | 含义 | 失败影响 |
|---|---|---|
| P0 | 第一版基线和当前发布必须通过，失败会破坏主闭环或写错学习状态 | 阻塞发布 |
| P1 | 重要体验或稳定性，失败会造成明显误导或重复操作 | 发布前必须修复或明确降级 |
| P2 | 优化项、边缘路径、文案和体验一致性 | 可带已知问题发布 |

## 总体通过标准

- P0 用例 100% 通过。
- P1 用例通过率不低于 95%，且不能存在会误写 `Attempt`、`ReviewState`、`due_at` 的缺陷。
- P2 用例完成评估并记录结论。
- API 契约测试必须覆盖成功、失败、缺字段、枚举非法和 `unsupported`。
- Agent 评分 JSON 必须通过 schema、枚举、分数合计、硬门槛和 FSRS 映射校验。
- LLM 输出质量测试不得出现虚构运行结果、泄露隐藏测试、跳过硬门槛判定或直接给完整答案冒充轻提示。

## 测试分层

| 层级 | 类型 | 目标 | 示例 |
|---|---|---|---|
| L0 | 单元 / 规则测试 | 校验纯规则和数据转换 | `result` 到 `fsrs_rating` 映射 |
| L1 | API 契约测试 | 校验请求响应、错误码、枚举与幂等 | `/run`、`/submit`、`/reviews/{session_id}/exercise-result` |
| L2 | 集成测试 | 校验 runner、Agent 状态机、写库时机 | `run_exercise -> evaluate_attempt -> update_review_state` |
| L3 | E2E 流程测试 | 校验用户能完成闭环 | Onboarding、学习、复习、恢复学习 |
| L4 | 前端手工 QA | 校验加载、空态、错误、禁用、确认、视觉边界 | 工作台、复习页、笔记抽屉、笔记页、设置页 |
| L5 | LLM 质量评测 | 校验 Agent 输出是否结构化、证据一致、可执行 | 错因解释、提示、代码解释检查 |

## 核心用户流程验收

| ID | 优先级 | 流程 | 前置条件 | 步骤 | 通过标准 |
|---|---|---|---|---|---|
| UF-01 | P0 | 首次建档：模糊目标模式 | 无活动计划 | 输入目标 -> 每轮单一澄清 -> 生成路线卡片 -> 可直接输入修订 -> 最新卡片点击 `开始学习` | 普通回复不展开整段路线；创建正式 `plan`，进入工作台，左侧路线面板有模块；旧卡片按钮禁用；`source_attribution` 可区分动态文档参考、用户资料或模板 fallback |
| UF-02 | P1 | 首次建档：参考资料模式 | 有课程目录或代码片段 | 粘贴资料 -> 生成草稿 -> 标注来源与 Agent 补充 | 用户能区分资料来源和新增内容 |
| UF-03 | P0 | 日常进入应用 | 已有活动计划 | 打开应用 -> 加载 dashboard | 5 秒内默认进入当前学习，展示当前阶段、今日任务、复习数量和复习提示 |
| UF-04 | P0 | 学习闭环 | 有 `browser_preview` 或 `python_stdout_test` 练习 | 进入知识点 -> 查看 `show_concept_intro` -> 自然语言判断 -> `show_concept_check_result` -> 对话中生成练习 UI -> 补全 -> 运行/预览/测试 -> 提交 -> 查看反馈 | 前端不暴露 run/submit 内部 Attempt 类型；概念卡和判断结果可刷新重放；后端生成可追溯 `Attempt`、`code_completion_result`，状态写回知识点 |
| UF-05 | P0 | 运行失败后错因解释 | 练习会产生失败测试或 runtime error | run 失败 -> 点击解释错误 -> 修改 -> rerun | 错因来自真实错误，旧结果标记 stale，新 Attempt 可追踪 |
| UF-06 | P0 | 复习闭环 | `ReviewState.due_at` 到期 | 进入复习 -> 短热身或跳过 -> 完成 seed bank 变体 -> submit | warmup 结果可刷新重放但不更新 FSRS；提交写入 `Attempt(review_submit)` 后更新 `fsrs_rating`、`due_at`、`forget_risk`，列表即时刷新 |
| UF-07 | P1 | 笔记抽屉 | 学习或复习会话进行中 | 打开笔记抽屉 -> 输入错因和修正方式 -> 自动保存 -> 请求 Agent 辅助补全 | 笔记不打断代码练习，保存状态明确，Agent 不自动生成完整笔记 |
| UF-08 | P1 | 笔记页 | 已有学习目标或知识点 | 进入笔记页 -> 按语言/知识点选择笔记 -> 编辑 Markdown -> 保存 | 笔记绑定知识点，复习和学习共用同一份笔记，不存在独立草稿生成流程 |
| UF-09 | P0 | 恢复中断学习 | 有历史会话摘要 | 打开应用 -> 调用 dashboard/resume -> 展示上次停留点和复习提示 | 普通打开默认当前学习；仅中断多日且复习高风险时优先进入复习 |
| UF-10 | P1 | Compiled language 能力边界 | 选择 Java / Go / C# 课程或尝试 C++ / Rust | 进入练习页或 Onboarding 错误 | Java / Go / C# 只展示 `managed_compiled_test` teaching-grade 单练习能力；C++ / Rust 返回 unsupported，不承诺完整项目/在线编译沙箱 |
| UF-11 | P1 | 设置页分类与边界 | 应用已完成初始化 | 进入设置 -> 切换外观、模型设置、学习偏好、复习、通知设置、记录与隐私、关于与诊断 | 分类完整；不能修改后端评分、Attempt 必填事实记录或 FSRS 固定规则 |

## API 契约测试

### 通用规则

- 所有响应失败时使用统一结构：

```json
{
  "error": {
    "code": "PLAN_NOT_FOUND",
    "message": "学习计划不存在"
  }
}
```

- 枚举字段必须拒绝非法值。
- 必填字段缺失必须返回明确 `error.code`。
- 幂等接口重复请求不得重复写入完成状态。
- 写库失败时不得向前端返回已完成学习或已完成复习。
- 前端验收不暴露 `Attempt(run)` / `Attempt(submit)`，但 API 和数据库验收必须能区分运行事实与提交事实。

### P0 API 清单

| API | 必测内容 |
|---|---|
| `POST /api/plans/generate` | `goal_based`、`material_based`、缺少目标、runtime 能力提示、动态路线生成成功、动态失败 fallback、`source_attribution` |
| `POST /api/plans` | `plan_draft` 确认、重复提交、草稿无效 |
| `GET /api/dashboard` | 活动目标、阶段、复习数量、恢复入口 |
| `POST /api/learning-sessions/start` | 新会话返回并持久化 `show_concept_intro`、已有未结束会话幂等返回、非法概念开场返回 `CONCEPT_INTRO_GENERATION_FAILED` |
| `POST /api/learning-sessions/{session_id}/messages` | `correct`、`incorrect`、`unclear`、`skipped` 概念判断，`concept_repair` 上限，引导练习和 tool-call 幂等重放 |
| `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run` | `success`、`runtime_error`、`timeout`、`unsupported` |
| `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit` | `passed`、`partial`、`failed`、`easy` 和硬门槛 |
| `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/hint` | `nudge`、`concept`、`code_shape`、提示次数累加 |
| `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error` | 错因分类、修复建议、关联知识点 |
| `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/check-explanation` | 最多 2 轮、`follow_up_required` |
| `GET /api/reviews/today` | 空复习、到期排序、`due_at` |
| `POST /api/reviews/start` | `warmup`、`review_stage`、`review_stage_state`、`selected_seed_id`、seed bank ready/replay、同步 rescue 成功、`REVIEW_SEED_BANK_GENERATION_FAILED` 不返回 fallback 题、`variant_reason` |
| `POST /api/reviews/{session_id}/warmup-result` | `correct`、`incorrect`、`unclear`、`skipped` 四类分支，最多一次 `warmup_repair`，不写 `Attempt` / `review_logs` / `ReviewState` |
| `POST /api/reviews/{session_id}/exercise-result` | `code_blank`、`fix_bug`、`explain_code`、`implement_function`、`review_ai_patch`，FSRS Rating、`due_at`、`forget_risk`、幂等不重复增加 `review_count` |
| `GET /api/learning-sessions/resume` | 最近摘要、`next_entry_point`、当前模块 |
| `GET /api/notes` | 按语言或知识点读取笔记、空笔记状态 |
| `POST /api/notes` | 创建知识点笔记、重复创建幂等或明确冲突 |
| `PATCH /api/notes/{note_id}` | Markdown 保存、保存失败不丢内容 |
| `GET /api/users/{user_id}` | 用户偏好、设置分类、诊断状态 |
| `PATCH /api/users/{user_id}/preferences` | 保存允许项，拒绝评分、Attempt、FSRS 固定规则修改 |

### 契约通过标准

- 每个 P0 API 至少有一个成功样例和一个失败样例。
- 动态路线生成不得改变 `PlanDraft` 公共结构；fallback 成功时仍返回 2xx 和可确认草稿，fallback 失败时返回稳定错误码，不暴露 provider 原始错误。
- 学习页概念开场和判断结果必须作为 `metadata.tool_calls` 持久化；刷新、恢复或 `client_message_id` 重放不得生成漂移内容。
- `CONCEPT_INTRO_GENERATION_FAILED` 不得落库破损 `show_concept_intro`，也不得暴露 raw provider error、raw prompt、SDK internals 或 secrets。
- `runtime_status` 只能是 `success` / `runtime_error` / `timeout` / `unsupported`。
- `result` 只能是 `failed` / `partial` / `passed` / `easy`。
- `fsrs_rating` 只能是 `Again` / `Hard` / `Good` / `Easy`。
- `score_breakdown` 四项分数均在 0-2，且 `score` 等于总和。
- `test_pass_rate < 0.8` 或关键测试失败时，不得返回 `passed` / `easy`。

## 代码补全验证与运行反馈验收

| ID | 优先级 | 场景 | 输入 | 通过标准 |
|---|---|---|---|---|
| CE-01 | P0 | JS/HTML/CSS 预览成功 | DOM 点击计数题，补全正确 | `runtime_status=success`，预览更新，测试通过 |
| CE-02 | P0 | JS 隐藏测试失败 | 只通过可见测试 | `test_pass_rate < 1`，不泄露隐藏测试源码，最高 `partial` |
| CE-03 | P0 | Python stdout 成功 | 函数返回或 print 正确 | stdout/test 展示正确，生成 Attempt |
| CE-04 | P0 | Python 运行错误 | 语法或类型错误 | 展示 stderr，`explain-error` 能定位错误类别 |
| CE-05 | P0 | 核心空缺错误 | `CodeBlank` 核心项错误 | `core_blank_gate=false`，结果为 `failed` |
| CE-06 | P0 | 测试全过但解释失败 | `test_pass_rate=1.0`，解释矛盾 | 最高 `partial`，触发追问或重点复习 |
| CE-07 | P1 | 使用多次提示后通过 | `hint_usage_count > 2` | `fsrs_rating` 降级为 `Hard` 或不高于 `Good` |
| CE-08 | P0 | C++/Rust unsupported / compiled managed languages | C++ / Rust 不出现在公开课程；Java / Go / C# 为 `managed_compiled_test` | C++ / Rust 选择返回不支持；Java / Go / C# 覆盖 `missing_toolchain`、`compile_error`、`runtime_error`、`timeout`、`test_failure`、`success`，不把缺 toolchain 写成完成态 |
| CE-09 | P1 | 运行结果 stale | run 后修改代码 | 旧测试结果标记 stale，提交前提示重新运行 |
| CE-10 | P0 | runner 写库失败 | Attempt 写入后 ReviewState 写入失败 | 前端不显示复习完成，可重试且不重复运行 |
| CE-11 | P0 | AI 补丁审核弱证据 | `review_ai_patch` verdict 正确但 evidence 只写 `tests passed` | `score_breakdown.evidence_grounding < 2`，结果不高于 `partial`，`fsrs_rating=Hard`，不得返回 `Easy` |

## FSRS 调度测试

| ID | 优先级 | 场景 | 通过标准 |
|---|---|---|---|
| FSRS-01 | P0 | `failed` 映射 | `fsrs_rating=Again`，`lapse_count` 增加或保持正确 |
| FSRS-02 | P0 | `partial` 映射 | `fsrs_rating=Hard`，`due_at` 保持短间隔 |
| FSRS-03 | P0 | `passed` 且低提示低错误 | `fsrs_rating=Good`，正常拉长间隔 |
| FSRS-04 | P0 | `easy` 且无提示无错误 | `fsrs_rating=Easy`，明显拉长间隔 |
| FSRS-05 | P0 | 仅 run 未 submit | 不更新 `ReviewState` |
| FSRS-06 | P0 | 复习 warmup 正确、错误、不明确或跳过 | 只更新 `learning_sessions.review_stage_state_json`，不创建 `Attempt`，不写 `review_logs`，不更新 `ReviewState` |
| FSRS-07 | P0 | 复习提交成功 | 写入 `last_review_at`、`review_count`、`last_attempt_id`、`last_fsrs_rating` |
| FSRS-08 | P1 | 时区边界 | `due_at` 在用户本地日期展示正确 |
| FSRS-09 | P1 | 恢复学习入口 | 普通打开只提示复习；仅中断多日且复习高风险时优先进入复习 |

## Agent 输出质量测试

### 确定性校验

这些测试必须自动化，失败即不通过：

- LLM 输出必须是可解析 JSON。
- 枚举值必须合法。
- `score` 必须等于 `completion_correctness + runtime_and_tests + error_diagnosis + explanation_check`。
- 四个分项分数必须在 0-2。
- 硬门槛失败时，`result` 不得为 `passed` 或 `easy`。
- `result` 与 `fsrs_rating` 映射不得冲突。
- `feedback` 不得虚构不存在的测试、stdout、stderr 或代码行为。
- `review_ai_patch` 输出必须包含 `verdict_correctness`、`evidence_grounding`、`knowledge_point_alignment`、`actionability` 四项，且弱证据不得映射为 `Easy`。

### 质量 rubric

LLM 输出质量单独用固定样例集评估，至少覆盖 JS/HTML/CSS、Python、运行错误、测试失败、解释失败、提示过多、复习变体。

| 维度 | 分值 | 通过要求 |
|---|---:|---|
| 证据一致性 | 0-2 | 必须引用真实运行/测试/错误事实，不虚构 |
| 反馈可执行性 | 0-2 | 指出具体代码位置、概念或下一步动作 |
| 提示边界 | 0-2 | `nudge` 不给答案，`code_shape` 不直接替用户完成全题 |
| 错因分类准确性 | 0-2 | 错因标签与失败原因一致 |
| 语言简洁度 | 0-2 | 不输出冗长泛化教程 |

通过标准：

- 每条样例总分不低于 7/10。
- `证据一致性` 不得为 0。
- P0 样例集中不得出现泄露隐藏测试、忽略硬门槛或虚构运行结果。
- 对同一固定输入重复 3 次，结构校验通过率必须为 100%，质量 rubric 平均分不低于 8/10。

### `explain-error` 模型接入验收

- [ ] 使用第三方 OpenAI-compatible `.env` 配置后，`explain-error` 响应包含 `generation_source=llm`。
- [ ] 中转站类 provider 先通过 `GET /v1/models` 确认当前 key 实际可请求的模型名，再把其中一个模型名写入本机 `aearn/.env`。
- [ ] 对要求 Responses API streaming 的 provider，后端请求必须使用 `POST /v1/responses`、`stream=true` 和 JSON 输出约束；不得依赖旧的非流式 `/chat/completions`。
- [ ] 未配置、key 无效、provider 超时或模型返回非法 JSON 时，`explain-error` 返回 503，错误码为 `MODEL_UNAVAILABLE`，且不暴露 provider 原始错误。
- [ ] 同一 `attempt_id` 和同一错误上下文重复请求命中幂等记录，不再次调用模型。
- [ ] 模型输出不得泄露隐藏测试 case id、隐藏测试源码、参考答案、真实 API key 或 provider 原始错误。
- [ ] 本地默认测试不需要真实第三方 API key，模型成功/失败路径用 mock 覆盖。

## 前端手工 QA 清单

### 全局

- [ ] API 离线时顶部有明确提示，运行、提交、生成计划草稿和笔记辅助补全禁用。
- [ ] 所有 loading 状态不导致重复提交。
- [ ] 所有 error 状态显示 `error.code` 或可读错误。
- [ ] 离开未保存笔记、跳过模块、调整主干、清理记录时有 confirm。
- [ ] 代码修改后旧运行结果显示 stale。

### Onboarding

- [ ] 空输入不能生成计划。
- [ ] 生成 `plan_draft` 时按钮进入 loading。
- [ ] 已生成路线后补充时间预算会生成新版路线卡片并展示新的学习节奏。
- [ ] 动态路线生成开启时，路线来源展示或诊断信息可区分 `agent_generated`、用户资料和模板 fallback。
- [ ] 动态路线生成失败时可回退到已审核课程模板；没有已登记课程或安全 fallback 时展示可恢复错误，不承诺任意语言可运行。
- [ ] `compiled_sandbox_later` 课程展示能力边界。
- [ ] `is_skippable=false` 的模块不能跳过。
- [ ] 确认计划后进入工作台。

### 学习工作台

- [ ] 顶部展示目标、阶段、语言、复习数量、恢复入口。
- [ ] 左侧路线高亮当前模块和知识点。
- [ ] 新会话入口显示 `show_concept_intro` 概念卡，包含总结、例子和 2-4 个文本选项；选项不是强制按钮，composer 保持可用。
- [ ] `show_concept_check_result` 能展示正确、错误、模糊和跳过四类结果；错误路径展示更窄 `repair_check`，不直接解锁练习。
- [ ] 概念判断通过后，`开始练习` 生成 `show_code_exercise`，`practice_unlock_reason=concept_check_passed` 且 `learning_incomplete=false`。
- [ ] 用户直接要求练习或修正上限后进入引导练习时，练习卡明确显示概念未完成状态。
- [ ] `CONCEPT_INTRO_GENERATION_FAILED` 页面显示重试和返回路线动作，不展示破损概念卡。
- [ ] 代码编辑器、预览和测试结果出现在对话生成的练习 UI 中，而不是固定三栏页面。
- [ ] 前端按钮和文案只展示运行、预览、测试、提交结果，不暴露 `Attempt(run)` / `Attempt(submit)` 内部类型。
- [ ] JS/HTML/CSS 展示 `PreviewPane`，Python 展示 `StdoutPane`。
- [ ] C++ / Rust 返回 unsupported；Java / Go / C# managed compiled 状态按后端 `runtime_status` 展示。
- [ ] `run`、`submit`、`hint`、`explain-error`、`check-explanation` 的 loading 与错误互不覆盖。
- [ ] `score_breakdown`、`weak_points`、`next_action` 清晰展示。

### 复习窗口

- [ ] 无待复习项时展示空态和继续学习入口。
- [ ] 开始复习后展示短热身、`review_stage`、`variant_reason` 和 seed 变体。
- [ ] 热身正确、错误、不明确和跳过都能切换到正确阶段；热身不会显示 FSRS 变化。
- [ ] seed bank rescue 失败展示 `REVIEW_SEED_BANK_GENERATION_FAILED` 和重试入口，不展示 fallback 题。
- [ ] `review_ai_patch` 表单必须填写 verdict、evidence、knowledge point risk 和 next action，提交结果完全使用后端评分。
- [ ] 提交成功后列表移除或标记完成。
- [ ] 提交失败不得标记完成。
- [ ] 右侧指标展示 `due_at`、`forget_risk`、上次复习时间和掌握度。
- [ ] 复习练习复用对话生成式代码练习 UI。

### 笔记抽屉

- [ ] 学习和复习会话中都能打开当前知识点笔记抽屉。
- [ ] `未保存`、`保存中`、`已保存`、`保存失败` 状态可见。
- [ ] 保存失败时保留本地内容，不静默关闭抽屉。
- [ ] Agent 辅助补全只基于当前会话、代码、测试结果和用户已有笔记，不自动生成完整笔记。

### 笔记页

- [ ] 笔记按学习目标语言和知识点组织。
- [ ] Markdown 编辑器支持创建空笔记、编辑和保存。
- [ ] 学习会话和复习会话引用同一份知识点笔记。
- [ ] 页面不存在 `CodeDraftPage`、`publishDrawer`、面试讲述草稿或独立复盘草稿入口。

### 设置页面

- [ ] 保存时禁用重复提交。
- [ ] 字段级错误能定位到具体表单项。
- [ ] 外观、模型设置、学习偏好、复习、通知设置、记录与隐私、关于与诊断七类可切换。
- [ ] 模型设置页只说明后端 `.env` 模型配置和当前诊断状态，不保存真实 API key；学习偏好、讲解风格、提示风格、通知偏好等可编辑偏好能保存并重新读取。
- [ ] 设置页不出现修改后端评分、Attempt 必填事实记录或 FSRS 固定规则的开关。

## 发布验收门禁

### P0 门禁

- Onboarding、学习闭环、复习闭环、恢复学习全部通过。
- `/run`、`/submit`、`/exercise-result` 契约测试全部通过。
- `code_completion_result` 自动校验全部通过。
- FSRS 映射和 `ReviewState` 写入时机全部通过。
- TypeScript/SQL/Java/Go/C# 公开路线的 teaching-grade runner 边界清晰，C++/Rust 暂不支持公开路线且没有误导性入口。

### P1 门禁

- 笔记抽屉、笔记页、错误重试、stale 状态、confirm 状态通过。
- 前端手工 QA 的 P1 问题已修复或写入已知问题清单。
- LLM 质量 rubric 达到通过标准。

### P2 门禁

- 文案一致性、视觉 polish、边缘错误提示完成评估。

## Post-MVP / v1.1 增强验收

### 动态学习路线生成

- [ ] `PLAN_GENERATION_ENABLED=false` 时，`POST /api/plans/generate` 走第一版模板路径，响应结构不变。
- [ ] 模型配置完整且 fake plan generation client 返回合法 modules 时，响应中 modules 使用动态结果，`source_attribution` 标记动态生成来源。
- [ ] 动态输出缺少 modules、数量越界、非中文标题、非法 `temp_id`、guardrail 命中或工具超时时，服务回退到模板或已校验 candidate，不暴露 raw provider error。
- [ ] 未同步扩展 `Language`、数据库约束、课程 catalog 和 runtime boundary 的语言不能作为公开可确认计划。
- [ ] 新增语言正式上线前必须补 API 示例、数据库约束、catalog seed、runtime boundary、前端展示、P0/P1 验收和回滚策略。
- [ ] 未完成项不影响主闭环、不误写状态、不误导运行能力。

## 需要持续同步的字段与术语

以下字段变化会影响测试和前端验收，必须同步更新本计划：

- `plan_draft`
- `runtime_tier`
- `runtime_status`
- `run_mode`
- `Attempt`
- `code_completion_result`
- `score_breakdown`
- `hard_gates`
- `explanation_check`
- `hint_usage_count`
- `error_count`
- `fsrs_rating`
- `due_at`
- `next_entry_point`
