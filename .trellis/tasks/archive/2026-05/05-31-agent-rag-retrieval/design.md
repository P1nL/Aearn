# Technical Design: Agent RAG Retrieval

## Problem Analysis

The agent has no way to search for relevant teaching materials mid-conversation. `lesson_sources_json` URLs are injected verbatim into the prompt but never fetched or indexed. The agent cannot ground its explanations in specific documentation.

## Architecture Decision

**MVP: Postgres full-text search (tsvector) + structured chunks**

Rationale:
- Teaching materials are small per KP (lesson outline + exercise content = tens of chunks)
- Full-text search is built into Postgres — no new extensions or services
- No embedding API dependency (LLM is often disabled in dev)
- Upgrade path to pgvector is straightforward (add embedding column later)
- Sufficient for "find relevant concept explanation" queries within a KP's scope

## Storage: `teaching_chunks` table

```sql
CREATE TABLE IF NOT EXISTS teaching_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
  chunk_type text NOT NULL CHECK (chunk_type IN ('outline', 'example', 'explanation', 'source_note')),
  title text NOT NULL,
  content text NOT NULL,
  source_url text,
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(content, '')), 'B')
  ) STORED,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_teaching_chunks_kp ON teaching_chunks(knowledge_point_id);
CREATE INDEX IF NOT EXISTS idx_teaching_chunks_search ON teaching_chunks USING GIN(search_vector);
```

## Indexing Strategy

Chunks are created from existing data (no URL fetching for MVP):
1. `lesson_outline_json` → one chunk per outline section (type: 'outline')
2. Exercise `prompt_markdown` + `solution_reference` → one chunk per exercise (type: 'example')
3. `lesson_sources_json` URLs → stored as source_note chunks with URL attribution (content = title only)

Indexing happens:
- On session start (if KP has no chunks yet)
- Can be triggered manually via Celery task later

## Agent Tool

```python
@function_tool(name_override="search_teaching_materials")
def search_teaching_materials(query: str, top_k: int = 3) -> dict[str, object]:
    """Search indexed teaching materials for the current knowledge point."""
```

Returns: list of {title, content, source_url, chunk_type, relevance_rank}

## Files to Create

- `app/services/teaching_chunks.py` — indexing + search logic
- `tests/test_teaching_chunks.py` — unit tests

## Files to Modify

- `app/db/schema.sql` — add teaching_chunks table
- `app/agents/tools.py` — add search_teaching_materials tool + LearningToolContext.knowledge_point_id field
