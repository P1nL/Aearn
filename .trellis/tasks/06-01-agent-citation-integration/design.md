# Agent citation integration design

## Architecture

Add `aearn/services/api/app/services/grounding_citations.py`. It converts retrieval results into a compact `AgentGroundingItem` payload suitable for future agent context injection.

## Contracts

Define:

- `GroundingCitation`: stable citation metadata for a chunk.
- `AgentGroundingItem`: bounded content snippet, citation, relevance score, match reasons.
- `grounding_results_for_agent(results, max_items=4, max_content_chars=800) -> tuple[AgentGroundingItem, ...]`

## Safety

The adapter bounds content snippets and carries source metadata instead of asking the model to infer attribution from prose. It does not format long verbatim source pages and does not add agent runtime browsing.

## Compatibility

This task does not modify production prompts yet. Later graph/agent tasks can consume the adapter output directly.

