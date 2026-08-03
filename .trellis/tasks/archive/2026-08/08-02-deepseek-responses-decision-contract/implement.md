# Implementation Plan: DeepSeek V4 Flash Responses 与 Tutor 决策契约

## Preflight

1. 检查 `llm_client.py`、`provider_gateway.py`、`contracts.py`、相关 tests/docs 的现有未提交 diff；复用正确的部分实现，不 reset 或覆盖它。
2. 重新核验当天官方 V4 Flash Responses 文档，将代码/tests 依赖的非敏感协议事实记录为 fixture/comment。
3. 在编辑前加载 `trellis-before-dev` 与 backend spec indexes。

## Ordered Work

1. 添加/集中 provider+exact-model protocol selector。
2. 只在确实共享语义时抽取 common Responses request/stream helper；不要复制粘贴 SSE parser。
3. 实现 DeepSeek V4 Flash Responses URL、payload 和 final event handling；其他 DeepSeek 保持 Chat Completions。
4. 强化 final visible-text extraction 与 invalid-response kinds，确保 reasoning-only 永远不是 content。
5. 扩展 `TutorDecision` typed contract、strict Pydantic envelope 与 canonical JSON helper，加入 `conversation_title`、`continuation_kind`。
6. 实现 normal terminal 与 explicit continuation 的 validation rules，不进入 Child 2 所属 lifecycle persistence。
7. 更新 primary gateway repair flow、低随机性与 safe diagnostic mappings。
8. 添加 fake transport/client tests；同步直接相关的 API/runtime docs。

## Focused Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_provider_gateway.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_sse.py -q
uv --directory .\aearn\services\api run ruff check app/services/llm app/services/tutor app/agents/harness tests/test_tutor_provider_gateway.py
uv --directory .\aearn\services\api run python -m mypy app
git diff --check
```

如果现有 generic LLM tests 覆盖共享 Responses parsing，也必须补跑。不得使用真实 credentials 或 live provider calls。

## Risk and Rollback

- 不得误把 `deepseek-v4-pro` 或任意 future alias 走到 V4 Flash Responses。
- 不得把 `reasoning_content` 作为 answer fallback。
- 不得把 safe diagnostic code 透过 public run/SSE payload 泄露。
- 文档化 Responses shape 若不能被安全解析，返回 selected-protocol safe error；不得 fallback 到 Chat Completions。
- typed contract 改动保持 additive，供 Child 2 在此 child 通过后消费。

## Completion Gate

- Child PRD/design/implement 的 acceptance 均被 focused fake-transport tests 证明。
- 当前 diff 通过检查且不存在 raw response/test-secret leakage。
- Parent 只记录 completion evidence；Child 2 必须等待本 child review/archive 后才能启动。
