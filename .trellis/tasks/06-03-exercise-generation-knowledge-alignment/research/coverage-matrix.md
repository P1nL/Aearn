# Exercise Generation Coverage Matrix

Generated from source inspection on 2026-06-03 and updated after implementation.

Primary sources:

- `aearn/services/api/app/services/curriculum/plan_generator.py`
- `aearn/services/api/app/services/runners/language_capabilities.py`
- `aearn/services/api/app/services/exercises/exercise_repository.py`
- `aearn/services/api/app/services/exercises/adaptive_exercise_service.py`
- `aearn/services/api/tests/test_adaptive_exercise_templates.py`

## Summary

- Public executable route languages: `python`, `javascript`, `html_css`, `typescript`, `sql`, `java`, `go`, `csharp`.
- Static placeholder only: `cpp`. It is not public and must not become publicly executable in this task.
- Initial audit found user-visible deterministic fallback behavior on provider/schema/runner failure; implementation now uses bounded retries and honest unavailable errors instead.
- Model context now includes `required_skill_tags`, lesson/module context, source taxonomy hints, runtime constraints, and safe retry feedback.
- Semantic validator coverage now exists across the public executable language set: Python `list_comprehension`; SQL `select`/`filtering`/`sorting`/`joins`/`aggregation`; JavaScript `functions`/`dom_events`; TypeScript `functions`/`types`; HTML/CSS structural and selector/layout markers; and Java/Go/C# lightweight managed-compiled `functions`/`types`/`control_flow` markers.

## Language Coverage Overview

| language | capability ids | runtime_tier | runner | route KPs | current internal seed / harness | model context coverage | semantic validator coverage | runner validation | known gap | priority |
|---|---|---|---|---:|---|---|---|---|---|---|
| `python` | `python` | `python_stdout_test` | `python` | 12 | Explicit deterministic Python seed in `_exercise_template()` with stdout/return visible tests. | Enhanced: `required_skill_tags`, route/module context, sources, weak points, runtime constraints, retry feedback. | Strict AST `list_comprehension` validator implemented. | Yes, through `run_exercise()` and Python runner. | Current seed is generic return/stdout and does not target every route tag; model-first generation must specialize. | P0 |
| `javascript` | `javascript` | `browser_preview` | `browser` | 12 | Uses browser-preview DOM counter seed. It is language/runtime compatible but generic. | Enhanced: `required_skill_tags`, route/module context, sources, weak points, runtime constraints, retry feedback. | Lightweight `functions` / `dom_events` validators implemented. | Yes, through browser preview runner. | Generic DOM counter can mismatch non-DOM JS KPs such as `types`, `strings`, `arrays`, `promises`; model-first generation must specialize. | P0 |
| `html_css` | `html`, `css` | `browser_preview` | `browser` | 12 | Explicit HTML/CSS static preview seed. | Enhanced: `required_skill_tags`, route/module context, sources, weak points, runtime constraints, retry feedback. | Lightweight structural/selectors/a11y/layout/responsive validators implemented. | Yes, through browser preview runner. | Seed is state-class oriented and can mismatch forms, layout, responsive, semantic HTML KPs; model-first generation must specialize. | P1 |
| `typescript` | `typescript` | `node_typescript_test` | `node` | 4 | Explicit Node/TypeScript seed with `entry_function=increment` and typed function tests. | Enhanced: `required_skill_tags`, route/module context, sources, weak points, runtime constraints, retry feedback. | Lightweight `functions` / `types` validators implemented. | Yes, through Node/TypeScript runner. | Seed covers typed increment only; model-first generation must specialize to each route KP. | P0 |
| `sql` | `sql` | `sql_query_test` | `sql` | 4 | Explicit SQLite query seed with SQL metadata and visible/hidden SQL tests. | Enhanced: `required_skill_tags`, route/module context, sources, weak points, runtime constraints, retry feedback. | Lightweight `select`, `filtering`, `sorting`, `joins`, `aggregation` validators implemented. | Yes, through SQL runner. | Current seed covers filtering/sorting only; model-first generation must specialize JOIN and aggregation KPs. | P0 |
| `java` | `java` | `managed_compiled_test` | `compiled` | 1 | Explicit Java managed-compiled seed. | Enhanced: `required_skill_tags`, route/module context, sources, weak points, runtime constraints, retry feedback. | Lightweight `functions`, `types`, `control_flow` markers implemented. | Yes when local JDK toolchain is available; unavailable result if missing. | Seed only covers method increment shape; strict parser remains deferred. | P1 |
| `go` | `go` | `managed_compiled_test` | `compiled` | 4 | Explicit Go single-package managed-compiled seed with `entry_function=Increment`. | Enhanced: `required_skill_tags`, route/module context, sources, weak points, runtime constraints, retry feedback. | Lightweight `functions`, `types`, `control_flow` markers implemented. | Yes when local Go toolchain is available; unavailable result if missing. | Seed covers increment only; model-first generation must specialize to each route KP. | P1 |
| `csharp` | `csharp` | `managed_compiled_test` | `compiled` | 4 | Explicit C# single-file managed-compiled seed with `Submission.Increment`. | Enhanced: `required_skill_tags`, route/module context, sources, weak points, runtime constraints, retry feedback. | Lightweight `functions`, `types`, `control_flow` markers implemented. | Yes when local .NET SDK is available; unavailable result if missing. | Seed covers increment only; model-first generation must specialize to each route KP. | P1 |
| `cpp` | `cpp` | `compiled_later` | `compiled` | 0 public KPs | Explicit static placeholder seed only. | Not applicable to public adaptive generation. | Not applicable. | No public execution. | Must remain static placeholder and not enter public executable validation. | Guardrail |

## First Validator Batch

| language | selected tags | validator style | reason |
|---|---|---|---|
| `python` | `list_comprehension` | Strict `ast` check for `ast.ListComp`. | High-value syntax marker with standard-library validation. |
| `sql` | `filtering`, `joins`, `aggregation` | Lightweight normalized-token checks for `WHERE`, `JOIN`, aggregate functions, and `GROUP BY`. | Covers current SQL route gaps without adding parser dependencies. |
| `javascript` | `functions`, `dom_events` | Lightweight marker checks for function syntax and DOM event binding. | Covers browser-preview route tags and current runner harness. |
| `typescript` | `functions`, `types` | Lightweight marker checks for function syntax and type annotations. | Covers Node/TypeScript public route without adding parser dependencies. |

## Extended Validator Batch

| language | selected tags | validator style | reason |
|---|---|---|---|
| `sql` | `select`, `sorting` | Lightweight normalized-token checks for `SELECT`/`FROM` and `ORDER BY`. | Covers remaining SQL route basics without parser dependencies. |
| `html_css` | `semantics`, `accessibility`, `forms`, `selectors`, `box_model`, `typography`, `state`, `layout`, `positioning`, `responsive` | Lightweight structural, attribute, selector, and CSS property checks. | Gives every HTML/CSS route family a bounded validation marker while strict parsing remains deferred. |
| `java` | `functions`, `types`, `control_flow` | Lightweight method/type/control-flow marker checks. | Covers Java managed-compiled route tags without adding parser dependencies. |
| `go` | `functions`, `types`, `control_flow` | Lightweight `func`, type signature, and control-flow marker checks. | Covers Go managed-compiled route tags without adding parser dependencies. |
| `csharp` | `functions`, `types`, `control_flow` | Lightweight method/type/control-flow marker checks. | Covers C# managed-compiled route tags without adding parser dependencies. |

## Knowledge Point Coverage

| language | module | knowledge_point_id | title | skill_tags | seed/harness status | validator status |
|---|---|---|---|---|---|---|
| `python` | Python 基础与值流动 | `kp_draft_python_values_expressions` | 值、表达式与名称 | `python`, `values` | Generic Python return/stdout seed only. | Not covered. |
| `python` | Python 基础与值流动 | `kp_draft_python_return_values` | 返回值与标准输出 | `function`, `stdout` | Generic Python return/stdout seed aligns partially. | Not covered. |
| `python` | 控制流与函数 | `kp_draft_python_condition_paths` | 条件路径 | `conditionals`, `debugging` | Generic Python return/stdout seed only. | Not covered. |
| `python` | 控制流与函数 | `kp_draft_python_function_arguments` | 函数参数与返回路径 | `functions`, `control_flow` | Generic Python return/stdout seed aligns partially. | Not covered. |
| `python` | 数据结构 | `kp_draft_python_sequence_operations` | 列表与序列操作 | `lists`, `sequences` | Generic Python return/stdout seed only. | Not covered. |
| `python` | 数据结构 | `kp_draft_python_mapping_transform` | 字典与集合查找 | `dicts`, `sets` | Generic Python return/stdout seed only. | Not covered. |
| `python` | 模块与输入输出 | `kp_draft_python_import_boundaries` | 导入与模块边界 | `modules`, `imports` | Generic Python return/stdout seed only. | Not covered. |
| `python` | 模块与输入输出 | `kp_draft_python_io_formatting` | 输入输出与格式化 | `io`, `stdout` | Generic Python return/stdout seed aligns partially. | Not covered. |
| `python` | 错误、异常与可见测试 | `kp_draft_python_traceback_reading` | 回溯信息阅读 | `exceptions`, `debugging` | Generic Python return/stdout seed only. | Not covered. |
| `python` | 错误、异常与可见测试 | `kp_draft_python_visible_tests` | 阅读可见测试失败 | `testing`, `debugging` | Generic Python return/stdout seed only. | Not covered. |
| `python` | 类与 AI 生成代码审查 | `kp_draft_python_class_shape` | 类的形状与对象状态 | `classes`, `objects` | Generic Python return/stdout seed only. | Not covered. |
| `python` | 类与 AI 生成代码审查 | `kp_draft_python_edge_examples` | 边界示例检查 | `testing`, `edge_cases` | Generic Python return/stdout seed only. | Not covered. |
| `javascript` | JavaScript 语言基础 | `kp_draft_js_values_variables` | 值、变量与类型 | `javascript`, `types` | Browser counter seed only. | Not covered. |
| `javascript` | JavaScript 语言基础 | `kp_draft_js_strings_arrays` | 字符串与索引集合 | `strings`, `arrays` | Browser counter seed only. | Not covered. |
| `javascript` | 控制流与函数 | `kp_draft_js_condition_loop` | 条件与循环 | `control_flow`, `loops` | Browser counter seed only. | Not covered. |
| `javascript` | 控制流与函数 | `kp_draft_js_function_contract` | 函数契约 | `functions`, `contracts` | Browser counter seed only. | Planned lightweight `functions`. |
| `javascript` | 对象与共享状态 | `kp_draft_js_object_access` | 对象属性访问 | `objects`, `state` | Browser counter seed aligns partially for state only. | Not covered. |
| `javascript` | 对象与共享状态 | `kp_draft_js_state_scope` | 回调间的状态作用域 | `state`, `scope` | Browser counter seed aligns partially for state only. | Not covered. |
| `javascript` | DOM 事件与共享状态 | `kp_draft_js_event_listener` | 事件监听器放置 | `dom`, `event` | Browser counter seed aligns. | Planned lightweight `dom_events`. |
| `javascript` | DOM 事件与共享状态 | `kp_draft_js_dom_updates` | DOM 查询与更新流程 | `dom`, `browser_preview` | Browser counter seed aligns. | Planned lightweight `dom_events`. |
| `javascript` | 异步行为与模块 | `kp_draft_js_promise_order` | Promise 时序 | `promises`, `async` | Browser counter seed only. | Not covered. |
| `javascript` | 异步行为与模块 | `kp_draft_js_module_boundaries` | 模块导入导出边界 | `modules`, `imports` | Browser counter seed only. | Not covered. |
| `javascript` | 验证 AI 生成的 DOM 代码 | `kp_draft_js_dom_assertions` | DOM 断言阅读 | `testing`, `dom` | Browser counter seed aligns partially. | Planned lightweight `dom_events`. |
| `javascript` | 验证 AI 生成的 DOM 代码 | `kp_draft_js_generated_code_review` | 生成代码审查 | `ai_review`, `verification` | Browser counter seed only. | Not covered. |
| `html_css` | HTML 文档结构 | `kp_draft_html_semantic_structure` | 语义结构 | `html`, `semantics` | HTML/CSS state-class seed only. | Implemented lightweight `semantics`. |
| `html_css` | HTML 文档结构 | `kp_draft_html_links_media` | 链接、图片与文本内容 | `html`, `content` | HTML/CSS state-class seed only. | Not covered. |
| `html_css` | 表单、控件与无障碍 | `kp_draft_html_accessible_controls` | 无障碍控件结构 | `html`, `accessibility` | HTML/CSS state-class seed only. | Implemented lightweight `accessibility`. |
| `html_css` | 表单、控件与无障碍 | `kp_draft_html_form_feedback` | 表单反馈结构 | `forms`, `accessibility` | HTML/CSS state-class seed only. | Implemented lightweight `forms` / `accessibility`. |
| `html_css` | CSS 选择器、层叠与盒模型 | `kp_draft_css_selector_specificity` | 选择器与优先级 | `css`, `selectors` | HTML/CSS state-class seed aligns partially for selectors. | Implemented lightweight `selectors`. |
| `html_css` | CSS 选择器、层叠与盒模型 | `kp_draft_css_box_model` | 盒模型间距 | `css`, `box_model` | HTML/CSS state-class seed only. | Implemented lightweight `box_model`. |
| `html_css` | 文本与视觉样式 | `kp_draft_css_text_hierarchy` | 文本层次 | `css`, `typography` | HTML/CSS state-class seed only. | Implemented lightweight `typography`. |
| `html_css` | 文本与视觉样式 | `kp_draft_css_state_class` | 状态类与选择器 | `css`, `state` | HTML/CSS state-class seed aligns. | Implemented lightweight `state`. |
| `html_css` | CSS 布局系统 | `kp_draft_css_flex_grid` | 弹性盒与网格布局 | `css`, `layout` | HTML/CSS state-class seed only. | Implemented lightweight `layout`. |
| `html_css` | CSS 布局系统 | `kp_draft_css_positioning` | 定位与溢出 | `css`, `positioning` | HTML/CSS state-class seed only. | Implemented lightweight `positioning`. |
| `html_css` | 响应式结构与视觉审查 | `kp_draft_css_responsive_breakpoints` | 响应式断点检查 | `css`, `responsive` | HTML/CSS state-class seed only. | Implemented lightweight `responsive`. |
| `html_css` | 响应式结构与视觉审查 | `kp_draft_html_visual_review` | 生成页面审查 | `html`, `css`, `ai_review` | HTML/CSS state-class seed only. | Not covered. |
| `typescript` | TypeScript 类型与函数契约 | `kp_draft_typescript_function_contract` | 函数契约与类型 | `typescript`, `functions`, `types` | Node/TypeScript typed increment seed available. | Implemented lightweight `functions` and `types`. |
| `typescript` | TypeScript 类型与函数契约 | `kp_draft_typescript_control_flow` | 控制流与边界输入 | `typescript`, `control_flow`, `testing` | Node/TypeScript typed increment seed available. | Not covered. |
| `typescript` | TypeScript 运行反馈与生成代码审查 | `kp_draft_typescript_runner_output` | 运行反馈阅读 | `typescript`, `runner`, `debugging` | Node/TypeScript typed increment seed available. | Not covered. |
| `typescript` | TypeScript 运行反馈与生成代码审查 | `kp_draft_typescript_generated_code_review` | 生成代码审查 | `typescript`, `ai_review`, `verification` | Node/TypeScript typed increment seed available. | Not covered. |
| `sql` | SQL 查询基础 | `kp_draft_sql_select_projection` | SELECT 与列投影 | `sql`, `select` | SQL seed aligns partially. | Implemented lightweight `select`. |
| `sql` | SQL 查询基础 | `kp_draft_sql_filter_order` | 过滤与排序 | `sql`, `filtering`, `sorting` | SQL seed aligns for `filtering` and `sorting`. | Implemented lightweight `filtering` / `sorting`. |
| `sql` | 关联、聚合与结果验证 | `kp_draft_sql_join_shape` | JOIN 结果形状 | `sql`, `joins` | SQL seed does not include JOIN. | Implemented lightweight `joins`. |
| `sql` | 关联、聚合与结果验证 | `kp_draft_sql_aggregate_assertions` | 聚合结果断言 | `sql`, `aggregation`, `testing` | SQL seed does not include aggregation. | Implemented lightweight `aggregation`. |
| `java` | Java 单文件函数练习 | `kp_draft_java_method_shape` | 方法形状与类型签名 | `java`, `types` | Java method seed aligns partially. | Implemented lightweight `types`. |
| `go` | Go 函数、类型与控制流 | `kp_draft_go_function_contract` | 函数契约与类型 | `go`, `functions`, `types` | Go managed-compiled increment seed available. | Implemented lightweight `functions` / `types`. |
| `go` | Go 函数、类型与控制流 | `kp_draft_go_control_flow` | 控制流与边界输入 | `go`, `control_flow`, `testing` | Go managed-compiled increment seed available. | Implemented lightweight `control_flow`. |
| `go` | Go 测试反馈与生成代码审查 | `kp_draft_go_runner_output` | 运行反馈阅读 | `go`, `runner`, `debugging` | Go managed-compiled increment seed available. | Deferred. |
| `go` | Go 测试反馈与生成代码审查 | `kp_draft_go_generated_code_review` | 生成代码审查 | `go`, `ai_review`, `verification` | Go managed-compiled increment seed available. | Deferred. |
| `csharp` | C# 方法、类型与控制流 | `kp_draft_csharp_function_contract` | 函数契约与类型 | `csharp`, `functions`, `types` | C# managed-compiled increment seed available. | Implemented lightweight `functions` / `types`. |
| `csharp` | C# 方法、类型与控制流 | `kp_draft_csharp_control_flow` | 控制流与边界输入 | `csharp`, `control_flow`, `testing` | C# managed-compiled increment seed available. | Implemented lightweight `control_flow`. |
| `csharp` | C# 运行反馈与生成代码审查 | `kp_draft_csharp_runner_output` | 运行反馈阅读 | `csharp`, `runner`, `debugging` | C# managed-compiled increment seed available. | Deferred. |
| `csharp` | C# 运行反馈与生成代码审查 | `kp_draft_csharp_generated_code_review` | 生成代码审查 | `csharp`, `ai_review`, `verification` | C# managed-compiled increment seed available. | Deferred. |
| `cpp` | Static placeholder only | N/A | N/A | N/A | Static placeholder only; not public. | Not applicable. |

## Implementation Implications

- Phase 1 must enrich model context before changing prompt behavior, otherwise semantic validators will receive too little evidence to distinguish generic drills from aligned exercises.
- Phase 2 must replace user-visible fallback behavior in adaptive generation. Deterministic payloads may remain as canonical seed/harness envelopes, but provider/schema/semantic/runner failure should retry then return an honest unavailable result.
- Phase 3 first batch proved the validator pipeline on Python, SQL, JavaScript, and TypeScript, then expanded lightweight validator coverage to Java, Go, C#, and HTML/CSS.
- TypeScript, Go, and C# now have runner-matching internal seed/harness coverage; strict parser-grade validators remain a follow-up, but lightweight semantic markers are implemented for every public executable language.
