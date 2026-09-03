# Feature Flag Inventory

- `TUTOR_THREAD_TURN_V2_ENABLED=true` 已存在，但 fresh DB 的 singleton cutover state 尚未启用，Desktop 因 `effective_enabled=false` 显示只读模式。
- Artifact 平台三个 gate 未写入 `.env`，因此使用代码默认 false：`TUTOR_LEARNING_ARTIFACTS_ENABLED`、`TUTOR_ARTIFACT_TEACHING_MODE_ENABLED`、`LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED`。
- `TUTOR_EXECUTOR_ENABLED`、`TUTOR_INFERRED_MEMORY_ENABLED`、planning/Codex/runtime/proactive flags 已为 true。
- `TUTOR_DEEPSEEK_RESPONSES_JSON_SCHEMA_ENABLED` 与 `RUNNER_COMPILED_SANDBOX_ENABLED` 不属于当前只读写入 authority，保持原值。
