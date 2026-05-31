# Learning Graph Real Orchestration Design

## Data Flow

1. Route validates and idempotency-checks the learning message.
2. Service loads current learning context and safe summaries.
3. Learning graph receives sanitized state.
4. Graph emits next stage and tool/persistence intents.
5. Service applies intents, builds the same public response, and stores idempotency result.

## Migration Strategy

Move one decision surface at a time into graph nodes, but do not archive this child until the learning page uses graph orchestration as the primary path.

## Rollback

Keep flag-off path until route-level learning tests pass under graph-enabled settings.
