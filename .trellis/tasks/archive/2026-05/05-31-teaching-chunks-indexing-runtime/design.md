# Teaching Chunks Indexing Runtime Design

## Boundaries

- `app/services/teaching_chunks.py` owns chunk extraction, indexing, and search helpers.
- Plan/exercise repositories own when source content becomes durable.
- Agent tools can call search only with server-owned `knowledge_point_id`.

## Data Flow

1. Plan or exercise content is persisted.
2. Service-owned code calls indexing for the affected knowledge point.
3. Indexing replaces or upserts chunk rows idempotently.
4. `search_teaching_materials` reads scoped chunks from the current knowledge point.

## Compatibility

- Indexing failure should not corrupt plan creation transactions.
- Search returns bounded fallback/empty results when no chunks exist.

## Rollback

Disable indexing calls; search tool remains available but returns no indexed rows.
