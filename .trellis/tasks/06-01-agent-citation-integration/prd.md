# Agent citation integration

## Goal

Expose retrieved official docs to agents and require clear source attribution without over-quoting or hiding uncertainty.

## Confirmed Facts

- `grounding_retrieval.py` returns ranked `GroundingRetrievalResult` values.
- `GroundingChunk` already includes source id, title, section path, canonical URL, source type, trust tier, fetched timestamp, and content hash.
- Runtime graph/agent orchestration wiring belongs to later `02-learning-graph-runtime-hardening`; this task should provide the agent-facing payload contract now.

## Requirements

- Add a safe agent-facing citation adapter for grounding retrieval results.
- Adapter output must include bounded supporting content plus citation metadata.
- Citation metadata must include stable citation id, source id, title, section path, canonical URL, source type, trust tier, content hash, and fetched timestamp.
- Adapter must preserve relevance score and match reasons for transparent source selection.
- Content snippets must be bounded and should not over-quote entire source chunks.
- Empty retrieval results must return an empty tuple.

## Acceptance Criteria

- [ ] Retrieval results convert into agent grounding items with citation metadata.
- [ ] Citation ids are deterministic for the same source URL/section/hash.
- [ ] Snippet content is bounded.
- [ ] Match reasons and relevance score survive conversion.
- [ ] Empty inputs degrade to empty outputs.
- [ ] No runtime SDK tool, route, or DB write is added.

## Out of Scope

- Prompt rewrites in production agents.
- UI citation rendering.
- Persistent citation storage.
- LangGraph runtime integration.
