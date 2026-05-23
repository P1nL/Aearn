# OpenAI Agents SDK Research Notes

Date: 2026-05-23

## Sources

- OpenAI Agents SDK intro: https://openai.github.io/openai-agents-python/
- OpenAI Agents SDK models: https://openai.github.io/openai-agents-python/models/
- OpenAI Agents SDK running agents: https://openai.github.io/openai-agents-python/running_agents/
- Upstream package metadata: https://raw.githubusercontent.com/openai/openai-agents-python/main/pyproject.toml

## Confirmed Upstream Facts

- Package name is `openai-agents`.
- Current upstream metadata observed during planning: version `0.17.3`.
- Requires Python `>=3.10`.
- Depends on `openai>=2.26.0,<3`.
- Core primitives are Agents, tools / agents-as-tools / handoffs, and guardrails.
- SDK includes built-in tracing, sessions, MCP server tool calling, and streaming runner APIs.
- SDK uses Responses API by default for OpenAI models.
- Official docs say many non-OpenAI providers still do not support Responses API; Chat Completions model support is available for those cases.
- Official docs warn that structured outputs may not be supported by some providers.

## Relevance To Aearn

- Aearn already has `openai==2.36.0` in the backend lock, so package dependency compatibility looks likely.
- Aearn should not fork the SDK. It should add it as a dependency and use local adapter protocols.
- SDK-managed sessions should not own Aearn's durable learning state in the first slice.
- The best first slice is a model-backed learning conversation adapter because it does not decide final grading or review scheduling.

## Open Follow-Up

- Confirm exact provider target before implementation. OpenAI platform and OpenAI-compatible proxies have different SDK setup paths.
