# SDK Agent Release Readiness

日期：2026-05-24
状态：Ready for local MVP use
范围：Teaching Agent、Exercise Coach、Note Assist、Review Coach、Onboarding Plan Agent 的 OpenAI Agents SDK 接入收口。

## 结论

Application-on-SDK 已通过本地 MVP release gate。SDK 层现在只负责生成和校验候选输出；模型不可用、候选为空、候选非法或 guardrail 阻断时，由 Aearn 的 service/repository/route 边界映射为 `MODEL_UNAVAILABLE`，API 契约、SSE frame、幂等记录和持久化写入仍由现有 service/repository 拥有。

本轮没有新增公开 provider diagnostics。当前可公开返回的信息仅限 `generation_source`、`generation_model` 这类非 secret 元数据；API/SSE 响应不得暴露 SDK event name、raw prompt、provider error body、API key、hidden test、`solution_reference` 或完整提交代码。

## Cross-Agent SDK Test Matrix

| Area | SDK success coverage | Failure / malformed behavior | Guardrail / leakage coverage | Contract / ownership coverage |
|---|---|---|---|---|
| Teaching messages | `tests/test_llm_integration.py::test_agents_sdk_learning_conversation_client_streams_text_deltas` | `tests/test_learning_sessions_m3.py::test_learning_message_llm_failure_returns_model_unavailable_without_provider_detail` | `tests/test_learning_sessions_m3.py::test_learning_message_json_guardrail_returns_model_unavailable_when_model_output_leaks` and `test_learning_message_sse_guardrail_error_after_partial_output` | JSON/SSE frames and idempotency in `tests/test_learning_sessions_m3.py` |
| Exercise Coach | `tests/test_llm_integration.py::test_agents_sdk_exercise_coach_client_streams_json_and_attaches_guardrails` and route SDK tests for hint/check | invalid check output rejection in `tests/test_llm_integration.py::test_sdk_explanation_check_rejects_invalid_output` | hidden identifier rejection in `test_sdk_error_explanation_rejects_output_that_leaks_hidden_identifier` | `Attempt` writes, hint counts, explanation fields, and submit scoring stay in `learning_session_repository.py` |
| Note Assist | `tests/test_llm_integration.py::test_agents_sdk_note_assist_client_streams_text_deltas_and_attaches_guardrails` | route-level `MODEL_UNAVAILABLE` in `tests/test_notes_m5.py::test_agent_draft_returns_model_unavailable_when_sdk_output_mentions_code_draft` | `test_note_assist_client_rejects_output_that_leaks_code_draft_wording` | JSON/SSE draft updates only `agent_draft`, covered by `tests/test_notes_m5.py` |
| Review Coach | `tests/test_llm_integration.py::test_agents_sdk_review_coach_client_streams_text_deltas_and_attaches_guardrails` | route-level `MODEL_UNAVAILABLE` in `tests/test_reviews_m4.py::test_review_start_returns_model_unavailable_when_sdk_review_text_leaks_answer` | `test_review_coach_sdk_response_rejects_output_that_leaks_hidden_identifier` | FSRS, `ReviewState`, `ReviewLog`, and `Attempt(review_submit)` writes stay in scheduler/repository tests |
| Onboarding Plan | `tests/test_llm_integration.py::test_agents_sdk_onboarding_plan_client_streams_json_and_attaches_guardrails` and `tests/test_onboarding_m2.py::test_generate_plan_uses_valid_sdk_candidate` | invalid SDK candidate rejection in `test_onboarding_plan_sdk_response_rejects_invalid_draft` | unsupported runtime claim rejection in `test_onboarding_plan_sdk_response_rejects_unsupported_runtime_claim` | `/api/plans/generate` remains draft-only and anchored to server-owned course templates; `POST /api/plans` owns `LearningPlan`, modules, knowledge points, review states, and idempotency |
| Dashboard / resume compatibility | Not SDK-backed | Not SDK-backed | Not SDK-backed | `tests/test_dashboard_resume_m6.py` proves SDK rollout did not break resume/dashboard contracts |

## Validation Results

| Command | Result |
|---|---|
| `uv --directory .\aearn\services\api run python -m pytest` | Pass: `83 passed, 2 warnings` |
| `uv --directory .\aearn\services\api run python -m mypy app` | Pass: `Success: no issues found in 50 source files` |
| `uv --directory .\aearn\services\api run ruff check app tests` | Pass: `All checks passed!` |
| `uv --directory .\aearn\services\api lock --check` | Pass: `Resolved 99 packages in 2ms` |
| `pnpm --dir .\aearn desktop:check` | Pass: `tsc && vite build`, 80 modules transformed |

## Residual Risks

- 本轮 fake SDK tests 证明集成、失败映射、guardrail 和契约稳定性，不证明真实模型的教学质量。
- 未执行真实 provider quality benchmark；真实模型输出质量仍需按 `docs/qa/acceptance-test-plan.md` 的 LLM rubric 单独抽样。
- 本地 release gate 通过不等于生产部署完成；生产部署、真实 key、provider 配额和延迟不在本任务范围内。
