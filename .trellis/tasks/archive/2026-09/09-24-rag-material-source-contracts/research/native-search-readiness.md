# Native search readiness investigation

2026-09-24. Planning/research only; no model requests, key reads, configuration changes or paid calls.

## Repository evidence

- aearn/services/api/app/agents/runtime/codex_config.py:21-23 pins provider aearn_deepseek, responses wire API and DEEPSEEK_API_KEY.
- Lines 135-145 require the exact deepseek-flash model and reject other provider values. Lines 165-180 generate isolated config, without explicit web_search enablement.
- codex_adapter.py:108-119 starts threads with that model/provider and validates returned identity. Aearn's sidecar does not inherit this development conversation's model/tools.

## Official documentation fetched directly over public HTTPS

- https://api-docs.deepseek.com/guides/responses_api/ : tools support table marks web_search and other built-in tools as ignored. Function tools supported. Restoring prior web_search_call items into context does NOT execute a new search.
- https://api-docs.deepseek.com/quick_start/agent_integrations/codex/ : sample explicitly sets web_search disabled, and describes built-in search as disabled for DeepSeek models. Catalog metadata mentioning a web search tool type is not execution support.
- These are documentation/static observations, not a live runtime negative test. No conclusion about unrelated DeepSeek consumer chat products.

## Decision required

Current pinned DeepSeek Responses route cannot be treated as the approved native-search fallback. Do not try to enable it merely by changing a prompt or metadata. Keep the existing teaching model unchanged. Proposed minimal extension: a separate discovery-only provider supporting native search, explicitly configured/authenticated with approved billing; return source candidates into the same source review/coverage flow. Do not reuse developer desktop credentials automatically. Concrete provider/account remains a user choice, not silently selected. If no extra provider is approved, report fallback unavailable rather than claiming course coverage complete.
