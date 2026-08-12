# 模型代码审核练习与预发布验证

## 目标

把“用户审核模型给出的代码”实现为当前 LearningTrack 的统一练习类型：系统根据语言、知识点、掌握度和历史误区生成需求与模型代码，用户提交结构化 findings，服务端确定性评分真实发现、遗漏、严重性、证据质量、验证方法、修改建议、重复项和误报。

## 背景

当前正式练习 authority 已位于 `aearn/services/api/app/services/learning/practice/`，并已接入 Lesson Gate、模块诊断、mastery evidence 与共享 executor。仓库仍保留一套旧 `review_ai_patch` 评分代码和文档，但它属于被替代的 review runtime，不能重新成为新产品的数据或 API authority。

本任务同时依赖已完成的统一 Action Runtime。模型生成题在发布前必须经过 parser、compile/typecheck、visible/hidden test、finding reachability 和 rubric consistency 校验；该校验必须作为受控 action 执行并引用 existing executor/domain authority。

## 依赖

- 已归档 `08-04-learning-track-plan-mastery-domain`。
- 已归档 `08-04-exercise-gates-execution-unlock`。
- 已归档 `08-12-tutor-authoritative-context-facts`。
- 已归档 `08-12-tutor-controlled-action-runtime`。
- 可被 `08-04-spaced-review-sessions` 消费，但本任务不拥有复习调度、FSRS 聚合或 ReviewSession finalization。

## 不可妥协边界

- 新正式 exercise type 使用 `model_code_review`，不恢复 `review_ai_patch` 旧路径。
- 学习者审核属于静态结构化评估；预发布阶段的代码执行不能被投影为“学习者已运行代码”。
- private rubric、expected findings、隐藏测试与完整 candidate 不进入公共 API、Tutor 普通上下文、trace、checkpoint、export 或 release evidence。
- 模型生成、教学反馈与 explanation 不能决定最终 score、pass、mastery evidence 或 unlock。
- 缺少受控 executor、Action Runtime verified receipt 或完整质量证据时，candidate 保持 draft/failed；不得发布未经验证题，也不得模板兜底冒充已验证题。

## 需求

### R1 — 题目 Contract

- `model_code_review` 题目包含需求、模型代码、语言/runtime 标签、审核范围、证据边界与提交 schema；不是让模型代审用户仓库或用户代码。
- 私有场景类型至少覆盖：一个 correctness issue、多个 correctness issues、只有改进项、完全正确、表面可疑但正确、修复一处引入回归。
- 场景类型、expected findings、reachability proof、隐藏测试和 rubric 只存在于 private authority，公共题面不暗示“必然有错”。
- 题目 version 与 private rubric version 不可变；修改题面、代码、expected finding、测试或评分策略必须发布新 version。
- `static_only` 题必须明确学习者提交阶段没有执行代码；可查看的预发布 evidence 只能来自已验证 receipt 的 learner-safe projection。

### R2 — 结构化 Finding

- 用户可提交 verdict、代码行范围、问题类型、严重性、触发条件、原理、影响、验证方法、修改建议和可选补充说明。
- verdict 至少支持 `correctness_issue`、`no_correctness_issue`、`improvement_only`、`uncertain`。
- 支持多个 finding，并以客户端稳定 finding id 关联反馈；服务端验证行范围、字段上限、verdict/finding shape 与 duplicate identity。
- `no_correctness_issue` 可以零 finding；`improvement_only` 只能提交 improvement finding；`correctness_issue` 必须至少包含一个非 improvement finding。
- 自由文本补充不能取代结构化字段，也不能影响服务端 matcher 的核心判断。

### R3 — 确定性评分与安全反馈

- 服务端使用版本化 rubric 对 expected findings 与用户 findings 做一对一确定性匹配，评分 discovery、omission、severity、evidence、validation method、suggested fix、duplicate 和 false positive。
- 完全正确或表面可疑但正确题对误报进行显著负向评分；只报告“看起来有问题”但无可验证证据不能通过。
- 只有改进项的题要区分 correctness issue 与 maintainability/performance/style improvement，不能把改进建议当 correctness bug。
- 提示、查看预发布 evidence、补救后提交与独立审核形成不同的 assistance/evidence summary；mastery 权重由服务端决定。
- 公共 score breakdown 只包含版本、维度分数、用户 finding 的 supported/partial/unsupported/duplicate 分类、遗漏等级和安全 next action，不返回 expected finding 文本、隐藏位置或测试内容。
- 可追加模型教学反馈，但输入只包含用户提交和 learner-safe 评分证据；模型反馈不得修改 deterministic result。

### R4 — 模型生成与预发布验证

- 生成输入只包含语言、knowledge/capability、目标难度、mastery 等级、受控误区标签和公开来源证据，不包含原始对话历史、secret 或用户身份信息。
- 生成结果先保存为 user/track/knowledge scoped draft candidate，公共题面和 private rubric 分离并各自计算 canonical hash。
- 预发布 action 为 exact descriptor `model-code-review.validate@1.0.0`，绑定 internal proactive Tutor run、`task_kind=model_code_review`、candidate hash、resource profile、timeout、retry、cancel、stale fence、verifier 和 receipt。
- parser、compile/typecheck、visible/hidden tests 复用现有 execution intent/job/executor；API 和 authoring worker 不直接启动 host process、Docker 或第二套 queue。
- finding reachability 必须证明每个 expected correctness finding 至少有一个确定性触发证据；rubric consistency 必须证明 matcher、严重性、verdict、场景类型和测试证据一致。
- 完全正确/表面可疑但正确题必须证明 expected correctness findings 为空，并满足版本化 coverage/adversarial policy；有错误题必须证明预期问题可触发且不存在先于目标问题的意外阻断错误。
- action verified 后才允许在一个事务中发布现有 `tutor_exercise_versions` 与 `tutor_exercise_private_rubrics`；candidate hash、validation authority hash 或 run scope 任一 stale 都拒绝发布。
- 校验失败记录稳定 failure code、安全摘要和 recovery；完整 provider body、异常、命令、路径、镜像或隐藏测试不得进入公共投影。

### R5 — 统一练习使用位置

- `model_code_review` 必须能被现有 Lesson Gate 与模块诊断消费，使用相同 ExerciseVersion、Attempt、result、mastery evidence 与 version/idempotency contract。
- 题目选择策略可根据 mastery、能力和误区调整难度、finding 数、干扰项和场景类型，但不能把 learner profile 写入公共题面。
- 为后续间隔复习与阶段综合训练提供稳定 exercise/result contract；本任务不恢复旧 review route，也不实现完整复习调度。
- Gate prepare 遇到需要动态生成的审核题时，返回 `preparing | ready | failed` 的服务端 authoring 状态；前端不自行生成或选择 fallback 题。

### R6 — Desktop 交互

- Lesson Gate 对 `model_code_review` 渲染需求、带行号模型代码、verdict 选择、finding 列表编辑和安全结果视图，不复用单一自由文本 textarea。
- 支持增加、删除和编辑 finding；提交前显示字段级错误，并保留用户未提交草稿。
- 只有服务端允许时显示提示或“查看验证证据”；查看结果后清楚标记 assisted 状态。
- 结果视图按用户 finding id 展示 supported/partial/unsupported/duplicate，显示维度分数与下一步，但不泄漏 expected finding 或隐藏测试。
- 390px、900px、1440px 下无水平溢出，代码区可横向滚动，表单可键盘操作，focus 可见并尊重 reduced motion。

## 验收标准

- [x] 用户能提交结构化 findings，以及“未发现 correctness issue”“只有改进项”和“不确定”结论。
- [x] 服务端能确定性区分真实发现、遗漏、重复、严重性错误和误报，并输出不泄露隐藏答案的 score breakdown。
- [x] 六类题目场景均有确定性 fixture，包含完全正确与表面可疑但正确的 false-positive 测试。
- [x] Python、JavaScript、TypeScript、SQL 至少各有一条通过完整预发布 gate 的审核题 fixture。
- [x] parser、compile/typecheck、visible/hidden test、finding reachability 或 rubric consistency 任一失败都会拒绝发布。
- [x] `model-code-review.validate@1.0.0` 复用统一 descriptor、resource policy、cancel/retry/verification/recovery、budget 和 receipt contract，且不修改核心 Action lifecycle 状态机。
- [x] 预发布执行复用现有 durable executor queue；没有 API/authoring worker host launch，也没有第二套 job lifecycle。
- [x] private candidate、expected finding、隐藏测试和 rubric 不进入公共 API、对话、trace、checkpoint、export、日志或 release evidence。
- [x] 同一幂等请求、重复 poll、Action retry、executor retry 和发布重放不会创建重复 candidate、job、exercise version、Attempt、result 或 mastery evidence。
- [x] Lesson Gate 与模块诊断可以消费 `model_code_review`；后续 ReviewSession 可以按稳定 contract 接入而无需读取旧 review authority。
- [x] 教学反馈引用用户具体 finding 与 learner-safe 验证证据，但最终评分不由自由模型文本决定。
- [x] API、PostgreSQL、Action Runtime、runner/executor、redaction、Desktop typecheck 与浏览器回归通过。

## 范围外

- 通用静态分析平台或对任意大型代码库进行安全审计。
- 用户上传自己的仓库、补丁或私有代码让模型代为 review。
- 恢复旧 `/api/reviews`、旧 `review_states`、旧 `review_logs` 或旧 `review_ai_patch` 前端。
- 实现完整间隔复习调度、FSRS finalization 或三栏学习工作区。
- 构建 reviewed container image fleet、发布生产镜像或批准生产 executor。
- 支持 Java、Go、C#、Rust、C++ 的完整预发布执行矩阵。
