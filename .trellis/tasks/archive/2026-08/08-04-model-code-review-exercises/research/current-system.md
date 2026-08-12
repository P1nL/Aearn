# 当前系统调研

## 调研结论

本任务应当扩展当前正式的 `learning/practice`、Tutor Action Runtime 与共享 executor，而不是恢复旧 `reviews` / `review_ai_patch` 运行时。新题型使用稳定值 `model_code_review`，作为现有 `ExerciseType`、Gate、Attempt 和模块诊断可消费的同一练习类型；旧实现只保留为评分经验和迁移审计材料。

## 当前正式 authority

### 练习与 Gate

- `app/services/learning/practice/contracts.py` 已定义不可变 `ExerciseVersion`、私有 `ExercisePrivateRubric`、Gate binding、Attempt result 与模块诊断 contract。
- `app/services/learning/practice/repository.py` 和 `service.py` 已拥有 Gate prepare/hint/attempt/poll、模块诊断、幂等、版本校验与服务端投影。
- `tutor_exercise_versions` 与 `tutor_exercise_private_rubrics` 已分离公共题面和私有评分事实；Attempt、submission、result、hint 与 execution link 为追加式事实。
- `LessonGatePanel.tsx` 当前只支持字符串 textarea，Desktop `ExerciseType` 只有 `code_completion | sql_query | browser_preview | static_code_reasoning`，因此结构化审核 UI 和运行时校验必须端到端新增。

### Tutor Action Runtime

- `ActionDescriptor` 已拥有输入/输出 schema、允许的 origin/task kind、resource profile、timeout、retry、verifier 与 recovery。
- `ControlledActionRuntime` 已完成 reserve/admit/run/verify、cancel、timeout、stale fence、预算和 receipt。
- `runner.execute` 只读取既有 durable job，不在 API adapter 中启动进程。
- 当前测试已经证明 `model-code-review.validate` descriptor 可以注册而不改变核心 lifecycle 状态机，但仍缺生产 descriptor、domain authority、adapter、verifier 和数据库约束。

### Lesson authoring 与用户范围

- Lesson 已有用户/track/knowledge scoped authoring run、provider attempt receipt、lease/recovery 和 background dispatch 模式。
- `tutor_conversations` 支持 `visibility=internal, kind=proactive`，`tutor_runs` 支持 `origin=proactive`，适合为预发布 Action 建立不进入学习者历史的内部控制 run。
- `tutor_run_learning_scopes.task_kind` 已允许 `model_code_review`，无需新增 task kind。

### 执行队列

- 当前 `tutor_execution_intents` / `tutor_execution_jobs` 只支持 Tutor effect 与 learner exercise attempt 两类 owner。
- 预发布 parser/compile/typecheck/test 若要复用 reviewed executor，需要 additive 新增 model review candidate/validation owner shape；不得创建第二套执行队列，也不得从 API 或 authoring worker 直接启动 host process/Docker。

## 旧实现的可复用经验与禁止事项

### 可复用经验

- `services/exercises/evaluation.py` 的旧审核评分证明了 verdict、证据、知识点风险和可执行建议应分维度评分。
- `docs/architecture/code-completion-evaluation-spec.md` 记录了“弱证据不能得到 Easy”等历史产品意图。
- 旧 fixture 可转写为新六场景确定性 fixture，但必须经过新 contract、private rubric 与预发布 gate。

### 禁止恢复

- 不恢复旧 `/api/reviews`、旧 `attempts.code_completion_result`、旧 `review_states` / `review_logs` 为新产品 authority。
- 不继续使用 `review_ai_patch` 作为当前正式 exercise type 名称。
- 不让模型自由文本决定最终 score、finding 匹配、通过或 mastery evidence。
- 不把 expected findings、隐藏测试、rubric、完整 provider payload 或 candidate 私有验证数据放入公共 API、Tutor context、trace、checkpoint、export 或 release evidence。

## 关键设计决定

1. 新 exercise type 为 `model_code_review`；学习者尝试属于 `static_only`，预发布阶段可以使用受控 executor，两者不能混为同一 execution claim。
2. 动态生成先写用户 scoped draft candidate；只有 `model-code-review.validate@1.0.0` 获得 verified receipt 后，才能原子发布到现有不可变 exercise/rubric authority。
3. 发布后的公共题面必须去个性化、不可包含学习者事实；用户 mastery/历史误区只用于选择难度、能力和陷阱，不写入题面。
4. Action 使用内部 proactive Tutor run、existing lease/fence/budget/receipt；authoring dispatcher 只推进 domain 状态，不实现第二套 action lifecycle。
5. 预发布执行 additive 复用现有 intent/job/executor，通过 owner/source one-of、复合 FK 和 trusted-input seam 固定 candidate/validation scope。
6. 结构化 submission 由服务端 canonicalize 后以 `structured_answer` 私有保存；字符串自由文本只允许作为补充字段。
7. 评分使用 deterministic expected-finding matching 与版本化权重；模型只能基于 learner-safe score evidence 生成补充教学反馈。

## 主要风险

- 动态生成题与现有共享 exercise version 的 scope 混淆，导致跨用户使用或个性化事实泄漏。
- 将预发布 executor 成功误当成学习者代码已经运行，产生错误 UI 披露。
- finding 文本匹配依赖模型，导致评分不可重放或隐藏 rubric 泄漏。
- 为预发布校验新建独立 queue/轮询状态机，绕过 Action Runtime 与现有 executor。
- Action receipt 成功但 candidate、validation job 或 rubric 已变化，发布 stale 版本。
- “完全正确/表面可疑但正确”fixture 覆盖不足，误报训练目标失真。

## 实施前需要冻结的接口

- `ModelCodeReviewSubmission`、`ModelReviewExpectedFinding`、`ModelReviewScoreBreakdown` 与 learner-safe per-finding feedback。
- candidate/authoring/validation 的数据库 identity、状态和 immutable hash。
- `model-code-review.validate@1.0.0` descriptor、authority kind、resource kinds、稳定 failure code。
- executor 的 `model_review_candidate` source 与 `model_review_validation` owner shape。
- Gate prepare 的 `preparing | ready | failed` 异步投影和 Desktop 结构化编辑状态。
