# Learning Agent Side Effects Wiring Design

## Boundaries

- `app/agents/tools.py` owns tool definitions and in-memory side-effect accumulation only.
- `app/services/learning_conversation.py` owns prompt/tool integration and returns agent response candidates.
- `app/routes/learning_sessions.py` and repository/service code own request facts, transaction timing, idempotency, and durable writes.

## Data Flow

1. Learning message endpoint loads session, knowledge point, and current exercise context.
2. Route/service creates `AgentSideEffects` and `LearningToolContext`.
3. Conversation builder receives the context and enables SDK teaching tools.
4. Agent tool calls append intents to `AgentSideEffects`.
5. Service-owned code serializes safe side-effect summaries or applies supported writes at a safe boundary.

## Compatibility

- Existing JSON/SSE payload keys remain stable.
- Side-effect metadata may be internal-only unless an existing response `metadata` bucket can carry safe summaries.
- Model unavailable behavior remains mapped to existing Aearn errors or deterministic fallback text.

## Rollback

Disable tool context construction and keep the existing `side_effects=None`, `tool_context=None` path.
