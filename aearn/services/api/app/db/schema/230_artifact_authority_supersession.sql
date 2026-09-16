-- Content-preserving retirement of an invalidated TeachingSession Artifact.
-- No rows or published content are rewritten by this schema upgrade.
CREATE OR REPLACE FUNCTION tutor_artifact_supersession_successor(p_artifact_id uuid)
RETURNS uuid AS $$
  WITH RECURSIVE descendants AS (
    SELECT child.*, 1 AS depth, ARRAY[a.teaching_session_id,child.id] AS lineage
    FROM tutor_learning_artifacts a
    JOIN tutor_teaching_sessions parent ON parent.id=a.teaching_session_id
      AND parent.user_id=a.user_id AND parent.conversation_id=a.conversation_id
      AND parent.track_id=a.learning_track_id AND parent.knowledge_key=a.knowledge_key
      AND parent.status='blocked'
    JOIN tutor_teaching_sessions child ON child.predecessor_session_id=parent.id
      AND child.user_id=parent.user_id AND child.conversation_id=parent.conversation_id
      AND child.track_id=parent.track_id AND child.knowledge_key=parent.knowledge_key
    WHERE a.id=p_artifact_id
    UNION ALL
    SELECT child.*, d.depth+1, d.lineage || child.id
    FROM descendants d
    JOIN tutor_teaching_sessions child ON child.predecessor_session_id=d.id
      AND child.user_id=d.user_id AND child.conversation_id=d.conversation_id
      AND child.track_id=d.track_id AND child.knowledge_key=d.knowledge_key
    WHERE d.status='blocked' AND d.depth<32 AND NOT child.id=ANY(d.lineage)
  )
  SELECT d.id FROM descendants d
  JOIN tutor_learning_tracks t ON t.id=d.track_id AND t.user_id=d.user_id
    AND t.version=d.track_version
  JOIN tutor_track_active_plans p ON p.track_id=d.track_id AND p.user_id=d.user_id
    AND p.revision_id=d.active_plan_revision_id
  JOIN tutor_track_node_progress progress ON progress.track_id=d.track_id
    AND progress.user_id=d.user_id AND progress.knowledge_key=d.knowledge_key
    AND progress.version=d.progress_version
  JOIN tutor_lesson_assignments assignment ON assignment.id=d.lesson_assignment_id
    AND assignment.user_id=d.user_id AND assignment.track_id=d.track_id
    AND assignment.knowledge_key=d.knowledge_key AND assignment.status='active'
    AND assignment.assignment_version=d.assignment_version AND assignment.document_id=d.document_id
  WHERE d.status IN ('active','paused','completed')
  ORDER BY d.depth DESC,d.created_at DESC,d.id DESC LIMIT 1;
$$ LANGUAGE sql STABLE STRICT;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_artifact_owner_scope()
RETURNS trigger AS $$
DECLARE
  session_row tutor_teaching_sessions%ROWTYPE;
  gate_row tutor_lesson_gate_states%ROWTYPE;
  review_item_row tutor_review_items%ROWTYPE;
  review_session_row tutor_review_sessions%ROWTYPE;
  item_version_row tutor_learning_item_versions%ROWTYPE;
  item_publication_row tutor_learning_item_publication_events%ROWTYPE;
  historical_supersession boolean := false;
  authority_session_version integer;
BEGIN
  SELECT * INTO session_row
  FROM tutor_teaching_sessions
  WHERE id=NEW.teaching_session_id
    AND user_id=NEW.user_id
    AND conversation_id=NEW.conversation_id
    AND track_id=NEW.learning_track_id
    AND knowledge_key=NEW.knowledge_key;
  -- Only a content-preserving terminal retirement may cross a blocked
  -- ancestor boundary. All Turn/Attempt/item checks below still run.
  IF TG_OP='UPDATE' THEN
   IF OLD.state IN ('pending','ready','active')
     AND NEW.state='superseded' AND NEW.version=OLD.version+1
     AND NEW.terminal_at IS NOT NULL AND NEW.allowed_actions_json='[]'::jsonb
     AND session_row.status='blocked'
     AND (to_jsonb(NEW)-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json'])
         IS NOT DISTINCT FROM
         (to_jsonb(OLD)-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json'])
     AND EXISTS (
       SELECT 1 FROM tutor_teaching_session_checkpoints c
       WHERE c.id=NEW.checkpoint_id AND c.teaching_session_id=NEW.teaching_session_id
         AND c.user_id=NEW.user_id AND c.conversation_id=NEW.conversation_id
     )
     AND (NEW.active_attempt_id IS NULL OR EXISTS (
       SELECT 1 FROM tutor_exercise_attempt_results r WHERE r.attempt_id=NEW.active_attempt_id
     ))
     AND tutor_artifact_supersession_successor(NEW.id) IS NOT NULL THEN
    historical_supersession := true;
   END IF;
  END IF;
  authority_session_version := session_row.version;
  IF historical_supersession THEN
    SELECT session_version INTO authority_session_version
    FROM tutor_teaching_session_checkpoints WHERE id=NEW.checkpoint_id;
  END IF;
  IF NOT historical_supersession AND (session_row.id IS NULL
     OR session_row.current_checkpoint_id IS DISTINCT FROM NEW.checkpoint_id
     OR session_row.track_version<>NEW.track_version
     OR session_row.progress_version<>NEW.progress_version
     OR session_row.assignment_version<>NEW.assignment_version
     OR session_row.status NOT IN ('active','paused')) THEN
    RAISE EXCEPTION 'Learning Artifact teaching authority is stale or mismatched'
      USING ERRCODE='23514';
  END IF;

  IF NEW.turn_id IS NOT NULL AND NOT EXISTS (
    SELECT 1
    FROM tutor_run_teaching_scopes AS scopes
    WHERE scopes.run_id=NEW.turn_id
      AND scopes.user_id=NEW.user_id
      AND scopes.conversation_id=NEW.conversation_id
      AND scopes.teaching_session_id=NEW.teaching_session_id
      AND scopes.track_id=NEW.learning_track_id
      AND scopes.knowledge_key=NEW.knowledge_key
      AND scopes.track_version=NEW.track_version
      AND scopes.progress_version=NEW.progress_version
      AND scopes.assignment_version=NEW.assignment_version
      AND (
        scopes.checkpoint_id=NEW.checkpoint_id
        OR EXISTS (
          SELECT 1
          FROM tutor_teaching_session_checkpoints AS produced
          WHERE produced.id=NEW.checkpoint_id
            AND produced.teaching_session_id=NEW.teaching_session_id
            AND produced.user_id=NEW.user_id
            AND produced.conversation_id=NEW.conversation_id
            AND produced.source_run_id=NEW.turn_id
            AND produced.predecessor_checkpoint_id=scopes.checkpoint_id
            AND produced.session_version=scopes.session_version+1
        )
      )
  ) THEN
    RAISE EXCEPTION 'Learning Artifact Turn scope is stale or mismatched'
      USING ERRCODE='23514';
  END IF;

  IF NEW.active_attempt_id IS NOT NULL
     AND NOT tutor_learning_artifact_attempt_owner_matches(
       NEW.user_id,
       NEW.conversation_id,
       NEW.learning_track_id,
       NEW.knowledge_key,
       NEW.teaching_session_id,
       NEW.owner_kind,
       NEW.owner_id,
       NEW.active_attempt_id
     ) THEN
    RAISE EXCEPTION 'Learning Artifact active Attempt owner scope is mismatched'
      USING ERRCODE='23514';
  END IF;

  IF NEW.owner_kind='lesson_gate' THEN
    SELECT * INTO gate_row
    FROM tutor_lesson_gate_states
    WHERE id=NEW.owner_id
      AND user_id=NEW.user_id
      AND track_id=NEW.learning_track_id
      AND knowledge_key=NEW.knowledge_key
      AND lesson_assignment_id=session_row.lesson_assignment_id;
    IF gate_row.id IS NULL
       OR (NOT historical_supersession AND gate_row.version<>NEW.owner_version)
       OR NEW.owner_context_version IS NOT NULL THEN
      RAISE EXCEPTION 'Learning Artifact Lesson Gate owner is stale or mismatched'
        USING ERRCODE='23514';
    END IF;
  ELSIF NEW.owner_kind='review_item' THEN
    SELECT * INTO review_item_row
    FROM tutor_review_items
    WHERE id=NEW.owner_id
      AND user_id=NEW.user_id
      AND track_id=NEW.learning_track_id
      AND knowledge_key=NEW.knowledge_key;
    IF review_item_row.id IS NULL
       OR (NOT historical_supersession AND review_item_row.version<>NEW.owner_version) THEN
      RAISE EXCEPTION 'Learning Artifact Review Item owner is stale or mismatched'
        USING ERRCODE='23514';
    END IF;
    SELECT * INTO review_session_row
    FROM tutor_review_sessions
    WHERE id=review_item_row.session_id
      AND user_id=NEW.user_id
      AND track_id=NEW.learning_track_id
      AND knowledge_key=NEW.knowledge_key;
    IF review_session_row.id IS NULL
       OR NEW.owner_context_version IS NULL
       OR (NOT historical_supersession AND review_session_row.version<>NEW.owner_context_version) THEN
      RAISE EXCEPTION 'Learning Artifact Review Session owner context is stale or mismatched'
        USING ERRCODE='23514';
    END IF;
  ELSIF NEW.owner_kind='teaching_practice' THEN
    IF NEW.owner_id IS DISTINCT FROM NEW.checkpoint_id
       OR NEW.owner_version IS DISTINCT FROM authority_session_version
       OR NEW.owner_context_version IS DISTINCT FROM authority_session_version THEN
      RAISE EXCEPTION 'Learning Artifact teaching owner is stale or mismatched'
        USING ERRCODE='23514';
    END IF;
  ELSIF NEW.owner_kind='learning_item' THEN
    SELECT * INTO item_version_row
    FROM tutor_learning_item_versions
    WHERE id=NEW.owner_id
      AND knowledge_key=tutor_plan_catalog_knowledge_key(
        NEW.user_id, NEW.learning_track_id, session_row.active_plan_revision_id, NEW.knowledge_key
      );
    IF item_version_row.id IS NULL
       OR NEW.owner_context_version IS DISTINCT FROM authority_session_version
       OR item_version_row.difficulty IS DISTINCT FROM NEW.difficulty
       OR (NEW.artifact_kind='test_result' AND NEW.purpose<>'result')
       OR (
         NEW.artifact_kind<>'test_result'
         AND (
           item_version_row.purpose IS DISTINCT FROM NEW.purpose
           OR (item_version_row.item_kind='code' AND NEW.artifact_kind<>'exercise_workspace')
           OR (item_version_row.item_kind='sql' AND NEW.artifact_kind<>'sql_workspace')
           OR (item_version_row.item_kind='demo' AND NEW.artifact_kind<>'demonstration')
           OR (item_version_row.item_kind='knowledge_check' AND NEW.artifact_kind<>'knowledge_check')
           OR (item_version_row.item_kind='model_review' AND NEW.artifact_kind<>'model_code_review')
         )
       ) THEN
      RAISE EXCEPTION 'Learning Artifact Learning Item owner is stale or mismatched'
        USING ERRCODE='23514';
    END IF;
    IF item_version_row.item_kind<>'demo' AND NOT EXISTS (
      SELECT 1
      FROM tutor_learning_item_practice_materializations AS materializations
      WHERE materializations.version_id=item_version_row.id
        AND materializations.item_handle=item_version_row.handle
        AND materializations.content_hash=item_version_row.content_hash
    ) THEN
      RAISE EXCEPTION 'Learning Artifact Learning Item lacks Practice authority'
        USING ERRCODE='23514';
    END IF;
    IF TG_OP='UPDATE'
       AND NEW.state IN ('completed','failed','cancelled','superseded') THEN
      IF NEW.owner_version IS DISTINCT FROM OLD.owner_version
         OR NEW.owner_context_version IS DISTINCT FROM OLD.owner_context_version
         OR NOT EXISTS (
           SELECT 1
           FROM tutor_learning_item_publication_events AS publication
           WHERE publication.version_id=item_version_row.id
             AND publication.state_version=NEW.owner_version
             AND publication.state='published'
         ) THEN
        RAISE EXCEPTION 'Learning Artifact terminal Learning Item owner is stale'
          USING ERRCODE='23514';
      END IF;
    ELSE
      SELECT * INTO item_publication_row
      FROM tutor_learning_item_publication_events
      WHERE version_id=item_version_row.id
      ORDER BY state_version DESC
      LIMIT 1;
      IF item_publication_row.id IS NULL
         OR item_publication_row.state<>'published'
         OR item_publication_row.state_version<>NEW.owner_version
         OR item_publication_row.item_handle<>item_version_row.handle
         OR item_publication_row.content_hash<>item_version_row.content_hash THEN
        RAISE EXCEPTION 'Learning Artifact Learning Item publication is stale'
          USING ERRCODE='23514';
      END IF;
    END IF;
  ELSE
    RAISE EXCEPTION 'Learning Artifact owner kind is invalid' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- The exception above is usable only with its append-only domain receipt.
-- A direct UPDATE lacking the matching terminal event fails at COMMIT.
CREATE OR REPLACE FUNCTION enforce_tutor_artifact_supersession_receipt()
RETURNS trigger AS $$
DECLARE successor uuid;
BEGIN
  IF NEW.state<>'superseded' OR OLD.state NOT IN ('pending','ready','active')
     OR NOT EXISTS (SELECT 1 FROM tutor_teaching_sessions s
                    WHERE s.id=NEW.teaching_session_id AND s.status='blocked') THEN
    RETURN NULL;
  END IF;
  successor := tutor_artifact_supersession_successor(NEW.id);
  IF successor IS NULL OR NOT EXISTS (
    SELECT 1 FROM tutor_learning_artifact_events e
    WHERE e.artifact_id=NEW.id AND e.user_id=NEW.user_id
      AND e.conversation_id=NEW.conversation_id AND e.event_kind='terminal'
      AND e.from_version=OLD.version AND e.to_version=NEW.version AND e.state='superseded'
      AND e.event_key='teaching-supersession:' || successor::text || ':' || NEW.id::text
      AND e.safe_payload_json->'owner_result'->>'reason_code'='teaching_authority_superseded'
      AND e.safe_payload_json->'owner_result'->>'predecessor_session_id'=NEW.teaching_session_id::text
      AND e.safe_payload_json->'owner_result'->>'successor_session_id'=successor::text
  ) THEN
    RAISE EXCEPTION 'Learning Artifact authority supersession requires its exact terminal receipt'
      USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_artifact_supersession_receipt ON tutor_learning_artifacts;
CREATE CONSTRAINT TRIGGER trg_tutor_artifact_supersession_receipt
AFTER UPDATE ON tutor_learning_artifacts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_artifact_supersession_receipt();
