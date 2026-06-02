# Managed compiled runners for Java, Go, and C# 审核稿

## 目标

把 Java、Go、C# 从 planned/static compiled runner 边界推进到 teaching-grade L3 本地执行，但仍然只面向单个教学练习，不做通用 IDE、项目执行、包管理器或在线沙箱。

## 范围

- 新增 Java/Go/C# managed compiled runner。
- 复用本机 toolchain detection，只检测 `javac`/`java`、`go`、`dotnet`，不自动安装。
- runner 必须使用临时目录、timeout、bounded stdout/stderr/error、hidden test redaction、temp path redaction。
- environment doctor、API contract、DB/runtime profile、desktop settings/runtime labels 必须和 runner 状态一致。
- Rust/C++ 继续不进入 L3 execution。

## 推荐合同

- 新增 runtime tier：`managed_compiled_test`。
- Java/Go/C# 使用 `runner_key="compiled"`，但只对这三种语言开放真实教学执行。
- `compiled_sandbox_later` 继续保留给 Rust/C++ 和静态/计划态 disclosure。
- 已确认把公开 runner result categories 稳定为：`missing_toolchain`、`unsupported`、`compile_error`、`runtime_error`、`timeout`、`test_failure`、`success`。

## 出题合同

继续遵循 P2 的 adaptive exercise 决定：由模型生成候选题，但不是自由出题。

- canonical template 负责 knowledge point、exercise type、runtime tier、harness shape、visible tests、hidden tests、scoring contract、fallback payload 和 safety constraints。
- 模型只在 canonical template envelope 内生成 candidate variant，可调整题面、变量名、数值、数据行和场景描述。
- 模型不能新增 Maven/Gradle/Go module/NuGet/.NET solution、外部依赖、隐藏测试语义、runtime contract 或 validation harness。
- 每个 Java/Go/C# candidate 必须先通过对应 managed compiled runner validation，验证通过后才可 materialize 或展示给 learner。
- 生成失败、输出非法、缺 toolchain、unsupported、compile error、runtime error、timeout 或 test failure 时，回退 stable canonical template。

## Dependencies

- 父任务：`.trellis/tasks/06-02-local-product-completion`，保持 `planning`，不要 start/archive。
- 已归档 coordination：`.trellis/tasks/archive/2026-06/06-02-06-language-l3-runner-contracts/prd.md`。
- 已完成 P2：local user data boundary、SQL runner、adaptive exercise template system。
- 现有 backend source of truth：`language_capabilities.py`、`runner_registry.py`、`runtime_runner.py`、`environment_doctor.py`。
- 现有 frontend disclosure：`SettingsPage.tsx`、`desktopLabels.ts`、`learningHelpers.ts`。

## Acceptance Criteria

- Java/Go/C# 覆盖 success、missing toolchain、compile error、runtime error、timeout、visible test failure、hidden test redaction、unsupported language。
- Java/Go/C# model-generated variants 遵循 P2：template-bounded、runner-validated、failure fallback；不展示未验证模型题。
- Rust/C++ 不能被 shared compiled runner 意外执行。
- 本机检测到 JDK/Go/.NET 不等于自动公开 executable claim。
- Java 只有在 runtime profile、course/exercise、tests、API/UI disclosure 全部同步后才可展示为可执行。
- Go/C# 默认仍不 public selectable；除非同一 task 同步扩展 Language literal、DB CHECK、catalog、course content、onboarding、API docs 和验收测试。
- 不支持 Maven/Gradle/Go module/NuGet/.NET solution 或任意项目执行。

## Execution Order

1. 锁定 `managed_compiled_test` 和 result category 合同。
2. 锁定 P2 出题合同：model-assisted candidate + canonical template + runner validation + fallback。
3. 先写 focused failing tests。
4. 实现 Java runner。
5. 实现 Go runner。
6. 实现 C# runner；如果 no-package 安全执行不可行，先保持 unsupported 并记录 blocker。
7. 同步 `language_capabilities`、`runner_registry`、`runtime_runner`。
8. 同步 `environment_doctor`、API docs/types、DB/runtime profile、desktop disclosure。
9. Java/Go/C# runner validation green 后再扩展 P2 adaptive template catalog。
10. 运行 focused pytest、`ruff`、`mypy`、`desktop:check`、`task.py validate`、`git diff --check`。

## Risks

- 直接扩展 `runtime_status` 会触及 DB CHECK、API docs、frontend `RuntimeStatus`、SSE 和 label helpers。
- C# 如果依赖 `dotnet restore` 或外部包源，可能违反 no-network/no-package 边界。
- Java 已是 public course language，最容易出现“课程可见”被误解成“可执行”的 UI/API 漂移。
- Go/C# runner ready 不等于 public course ready。

## Rollback Points

- 把 Java/Go/C# `LanguageCapability.execution` 回退到 `compiled_later`。
- 保留或回退新增 runtime profile，但不要让 course seed 引用它。
- 保持 `compiled_sandbox_later` unsupported fallback。
- 如果 C# 风险过大，可单独保留 C# planned，先完成 Java/Go。

## Resolved Decisions

- 采用 `managed_compiled_test`。
- 采用扩展公开 result categories。
- 出题遵循 P2：模型生成候选题，但必须 template-bounded、runner-validated，并有 canonical fallback。

## Implementation Status

- Java/Go/C# managed compiled runner 已实现，覆盖本机 toolchain detection、临时目录、bounded stdout/stderr/error、timeout、temp path redaction、hidden test redaction。
- Java 已同步到 public course/runtime profile，并提供单文件 `public class Main` 教学练习；Go/C# 仅有 runner/runtime capability，仍不 public selectable。
- Rust/C++ 继续走 `compiled_sandbox_later` / static disclosure；即使误传 `managed_compiled_test`，也不会 dispatch 到 managed runner。
- `runtime_status` 已扩展为 `missing_toolchain`、`unsupported`、`compile_error`、`runtime_error`、`timeout`、`test_failure`、`success`，并同步 DB/API/frontend types 和 labels。
- Learning submit gate 已收紧为最近一次非 stale 的 `visible_tests` 且 `runtime_status="success"`，不再只排除 `unsupported`。
- API/runtime docs 和 frontend interaction spec 已同步 managed compiled 边界、Go/C# 非公开边界、Rust/C++ non-exec 边界。

## Verification Status

- `uv --directory .\aearn\services\api run python -m pytest tests/test_managed_compiled_runner.py tests/test_runner_registry.py tests/test_environment_doctor.py tests/test_language_capabilities.py tests/test_onboarding_m2.py tests/test_learning_sessions_m3.py::test_managed_java_runtime_statuses_are_public_and_persisted tests/test_learning_sessions_m3.py::test_compiled_later_runtime_returns_unsupported_boundary tests/test_llm_integration.py tests/test_teaching_chunks.py -q` -> `116 passed`。
- `uv --directory .\aearn\services\api run ruff check .` -> passed。
- `uv --directory .\aearn\services\api run python -m mypy app` -> passed。
- `pnpm --dir .\aearn desktop:check` -> passed，保留既有 Vite chunk-size warning。
- `python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-02-managed-compiled-runners-java-go-csharp` -> passed。
- `git diff --check` -> passed，仅显示 Windows LF/CRLF 提示。
