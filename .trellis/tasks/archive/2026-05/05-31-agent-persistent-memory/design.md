# Technical Design: Agent Persistent Memory

## Problem Analysis

All learner context dies with the session. The agent cannot:
- Reference past struggles ("you had trouble with recursion last week")
- Adapt teaching style based on observed preferences
- Track error pattern frequency across sessions
- Build a longitudinal view of learner progress

## Architecture

### Storage: `learner_profiles` table

Separate table (not JSONB on users) because:
- Profile grows over time — separate table avoids bloating user queries
- Profile has its own update cadence (per-session, not per-user-edit)
- Easier to add indexes on profile fields later

```sql
CREATE TABLE IF NOT EXISTS learner_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  weak_points jsonb NOT NULL DEFAULT '[]'::jsonb,
  error_patterns jsonb NOT NULL DEFAULT '[]'::jsonb,
  learning_preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
  pace_indicators jsonb NOT NULL DEFAULT '{}'::jsonb,
  observations jsonb NOT NULL DEFAULT '[]'::jsonb,
  session_count integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT learner_profiles_user_id_key UNIQUE (user_id)
);
```

### Profile Schema (JSONB fields)

```python
weak_points: [
  {"area": "recursion", "evidence_count": 3, "last_seen": "2026-05-30", "confidence": "confirmed"},
  {"area": "scope", "evidence_count": 1, "last_seen": "2026-05-28", "confidence": "ambiguous"},
]

error_patterns: [
  {"pattern": "off_by_one", "frequency": 5, "last_seen": "2026-05-30", "confidence": "confirmed"},
  {"pattern": "type_coercion", "frequency": 2, "last_seen": "2026-05-29", "confidence": "ambiguous"},
]

learning_preferences: {
  "style": "examples_first",       # confirmed | ambiguous | null
  "feedback_verbosity": "concise", # confirmed | ambiguous | null
  "pace": "moderate",              # confirmed | ambiguous | null
}

pace_indicators: {
  "avg_attempts_per_exercise": 2.3,
  "avg_hints_per_exercise": 0.8,
  "sessions_completed": 12,
}

observations: [
  {"session_id": "...", "timestamp": "...", "type": "weak_point", "content": "struggled with closure scope", "confidence": "confirmed"},
  ...
]  # capped at last 50 observations
```

### Agent Tools

1. `get_learner_profile` — read tool, returns condensed profile for system prompt injection
2. `update_learner_profile` — write tool via side_effects accumulator, appends observations

### Integration Flow

```
Session start:
  → load learner_profile for user
  → inject condensed summary into agent system prompt
  → agent has cross-session context from first message

During session:
  → agent calls record_diagnosis (existing tool)
  → at session end, service layer extracts observations from diagnosis_updates
  → merges into learner_profile (increment counters, append observations, update timestamps)

Explicit agent action:
  → agent calls update_learner_profile with new observations
  → side_effects accumulates them
  → service layer commits at transaction boundary
```

### Profile Update Logic

Incremental merge, not overwrite:
- `weak_points`: if area exists, increment evidence_count + update last_seen; if new, append
- `error_patterns`: if pattern exists, increment frequency + update last_seen; if new, append
- `learning_preferences`: only update if new confidence >= existing confidence
- `observations`: append (FIFO, cap at 50)
- `session_count`: increment

## Files to Create

- `app/services/learner_profile.py` — repository + merge logic
- `app/db/migrations/add_learner_profiles.sql` — schema migration
- `tests/test_learner_profile.py` — unit + integration tests

## Files to Modify

- `app/agents/tools.py` — add `get_learner_profile` and `update_learner_profile` tools
- `app/services/learning_conversation.py` — inject profile into system prompt context
- `app/db/schema.sql` — add table definition

## Risk Mitigation

- Profile is additive context — if missing, agent works normally (just without cross-session memory)
- Observations are capped to prevent unbounded growth
- No breaking changes to existing session flow
