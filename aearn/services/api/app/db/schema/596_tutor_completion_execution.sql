-- Candidate only. Installed SQL <=595 remains immutable; Main owns installation.
-- Private request/result JSON is not a public event or generic diagnostic payload.
CREATE TABLE IF NOT EXISTS tutor_run_execution_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  predecessor_batch_id uuid UNIQUE,
  batch_index integer NOT NULL CHECK (batch_index > 0),
  owner_id text NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 160),
  owner_generation integer NOT NULL CHECK (owner_generation > 0),
  policy_fingerprint text NOT NULL CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'),
  issued_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  max_decisions integer NOT NULL DEFAULT 8 CHECK (max_decisions = 8),
  max_http_attempts integer NOT NULL DEFAULT 16 CHECK (max_http_attempts = 16),
  result_reserve_seconds integer NOT NULL DEFAULT 60 CHECK (result_reserve_seconds = 60),
  decision_count integer NOT NULL DEFAULT 0 CHECK (decision_count BETWEEN 0 AND 8),
  http_attempt_count integer NOT NULL DEFAULT 0 CHECK (http_attempt_count BETWEEN 0 AND 16),
  CHECK (expires_at > issued_at AND expires_at <= issued_at + interval '2400 seconds'),
  UNIQUE (run_id,batch_index),
  UNIQUE (id,run_id,user_id,conversation_id,input_revision),
  FOREIGN KEY (run_id,user_id) REFERENCES tutor_runs(id,user_id) ON DELETE RESTRICT,
  FOREIGN KEY (run_id,conversation_id) REFERENCES tutor_runs(id,conversation_id) ON DELETE RESTRICT,
  FOREIGN KEY (predecessor_batch_id,run_id,user_id,conversation_id,input_revision)
    REFERENCES tutor_run_execution_batches(id,run_id,user_id,conversation_id,input_revision) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_completion_batch_root
  ON tutor_run_execution_batches(run_id) WHERE predecessor_batch_id IS NULL;

CREATE TABLE IF NOT EXISTS tutor_run_step_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  batch_id uuid NOT NULL,
  step_key text NOT NULL CHECK (length(step_key) BETWEEN 1 AND 160),
  kind text NOT NULL CHECK (kind IN ('provider_decision','sidecar_turn')),
  decision_iteration integer NOT NULL CHECK (decision_iteration > 0),
  attempt_number integer NOT NULL CHECK (attempt_number > 0),
  predecessor_attempt_id uuid UNIQUE,
  owner_id text NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 160),
  owner_generation integer NOT NULL CHECK (owner_generation > 0),
  request_json jsonb NOT NULL CHECK (jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=8388608),
  dependencies_json jsonb NOT NULL CHECK (jsonb_typeof(dependencies_json)='object' AND octet_length(dependencies_json::text)<=8388608),
  capability_count_before integer NOT NULL CHECK (capability_count_before>=0),
  effect_count_before integer NOT NULL CHECK (effect_count_before>=0),
  state text NOT NULL DEFAULT 'prepared' CHECK (state IN
    ('prepared','dispatched','result_recorded','accepted','rejected','not_sent','outcome_unknown')),
  prepared_at timestamptz NOT NULL,
  dispatched_at timestamptz,
  observable_http_count integer NOT NULL DEFAULT 0 CHECK (observable_http_count BETWEEN 0 AND 64),
  http_batch_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(http_batch_ids_json)='array' AND jsonb_array_length(http_batch_ids_json)=observable_http_count),
  result_type text CHECK (result_type IN ('tutor_provider_result_v1','tutor_run_result_v1','runtime_planning_step_result_v1')),
  result_json jsonb CHECK (jsonb_typeof(result_json)='object' AND octet_length(result_json::text)<=8388608),
  result_recorded_at timestamptz,
  accepted_at timestamptz,
  accepted_owner_id text,
  accepted_owner_generation integer CHECK (accepted_owner_generation > 0),
  acceptance_batch_id uuid,
  diagnostic_code text CHECK (diagnostic_code ~ '^[A-Za-z0-9_]{1,120}$'),
  UNIQUE (id,run_id,user_id,conversation_id),
  UNIQUE (id,run_id,user_id,conversation_id,input_revision),
  UNIQUE (run_id,step_key,attempt_number),
  CHECK ((result_json IS NULL) = (result_type IS NULL)),
  CHECK ((result_json IS NULL) = (result_recorded_at IS NULL)),
  CHECK (result_json IS NULL OR state='outcome_unknown' OR NOT (
    strpos(COALESCE(result_json->>'safe_code',''),'_http_unknown_')>0
    OR jsonb_path_exists(result_json, '$.nested_http_outcomes[*] ? (@.outcome_unknown == true)')
  )),
  CHECK (result_json IS NULL OR
    (kind='provider_decision' AND result_type='tutor_provider_result_v1') OR
    (kind='sidecar_turn' AND result_type IN ('tutor_run_result_v1','runtime_planning_step_result_v1'))),
  CHECK ((state IN ('prepared','not_sent') AND dispatched_at IS NULL AND result_json IS NULL AND observable_http_count=0)
    OR (state='dispatched' AND dispatched_at IS NOT NULL AND result_json IS NULL)
    OR (state IN ('result_recorded','accepted','rejected') AND dispatched_at IS NOT NULL AND result_json IS NOT NULL)
    OR (state='outcome_unknown' AND dispatched_at IS NOT NULL)),
  CHECK ((state='accepted' AND accepted_at IS NOT NULL AND accepted_owner_id IS NOT NULL
        AND accepted_owner_generation IS NOT NULL AND acceptance_batch_id IS NOT NULL)
    OR (state<>'accepted' AND accepted_at IS NULL AND accepted_owner_id IS NULL
        AND accepted_owner_generation IS NULL AND acceptance_batch_id IS NULL)),
  FOREIGN KEY (run_id,user_id) REFERENCES tutor_runs(id,user_id) ON DELETE RESTRICT,
  FOREIGN KEY (run_id,conversation_id) REFERENCES tutor_runs(id,conversation_id) ON DELETE RESTRICT,
  FOREIGN KEY (batch_id,run_id,user_id,conversation_id,input_revision)
    REFERENCES tutor_run_execution_batches(id,run_id,user_id,conversation_id,input_revision) ON DELETE RESTRICT,
  FOREIGN KEY (acceptance_batch_id,run_id,user_id,conversation_id,input_revision)
    REFERENCES tutor_run_execution_batches(id,run_id,user_id,conversation_id,input_revision) ON DELETE RESTRICT,
  FOREIGN KEY (predecessor_attempt_id,run_id,user_id,conversation_id,input_revision)
    REFERENCES tutor_run_step_attempts(id,run_id,user_id,conversation_id,input_revision) ON DELETE RESTRICT
);
-- Unknown remains an active exclusion: lease expiry/new key cannot bypass it.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_completion_active_step
  ON tutor_run_step_attempts(run_id) WHERE state IN ('prepared','dispatched','result_recorded','outcome_unknown');
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_completion_step_root
  ON tutor_run_step_attempts(run_id,step_key) WHERE predecessor_attempt_id IS NULL;

CREATE OR REPLACE FUNCTION enforce_tutor_run_execution_batch()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  r tutor_runs%ROWTYPE;
  p tutor_run_execution_batches%ROWTYPE;
  t timestamptz;
BEGIN
  -- Forward protection only: no legacy UPDATE can opt an existing run into B.
  IF TG_TABLE_NAME='tutor_runs' THEN
    IF OLD.policy_json->>'execution_profile'='completion_driven_v1' AND
       (NEW.iteration_count<OLD.iteration_count OR NEW.model_call_count<OLD.model_call_count
        OR NEW.capability_call_count<OLD.capability_call_count OR NEW.effect_count<OLD.effect_count) THEN
      RAISE check_violation USING MESSAGE='completion cumulative counters cannot decrease';
    END IF;
    IF (OLD.policy_json->>'execution_profile'='completion_driven_v1'
        OR NEW.policy_json->>'execution_profile'='completion_driven_v1')
       AND (NEW.policy_json IS DISTINCT FROM OLD.policy_json
        OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
        OR NEW.policy_fingerprint IS DISTINCT FROM OLD.policy_fingerprint
        OR NEW.user_id IS DISTINCT FROM OLD.user_id
        OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
        OR NEW.catalog_digest IS DISTINCT FROM OLD.catalog_digest) THEN
      RAISE check_violation USING MESSAGE='completion run policy and scope are immutable';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE check_violation USING MESSAGE='completion batch deletion denied';
  END IF;
  IF TG_OP='UPDATE' THEN
    SELECT * INTO r FROM tutor_runs WHERE id=OLD.run_id FOR UPDATE;
    t:=clock_timestamp();
    IF NOT FOUND OR r.terminal_outcome IS NOT NULL OR r.cancelled_at IS NOT NULL
       OR r.superseded_by_run_id IS NOT NULL OR r.input_revision<>OLD.input_revision
       OR r.active_lease_owner_id IS DISTINCT FROM OLD.owner_id
       OR r.active_lease_generation<>OLD.owner_generation
       OR r.active_lease_expires_at IS NULL OR r.active_lease_expires_at<=t THEN
      RAISE check_violation USING MESSAGE='completion batch accounting current owner required';
    END IF;
    IF (to_jsonb(NEW)-ARRAY['decision_count','http_attempt_count']) IS DISTINCT FROM
       (to_jsonb(OLD)-ARRAY['decision_count','http_attempt_count'])
       OR NEW.decision_count NOT BETWEEN OLD.decision_count AND OLD.decision_count+1
       OR NEW.http_attempt_count NOT BETWEEN OLD.http_attempt_count AND OLD.http_attempt_count+1 THEN
      RAISE check_violation USING MESSAGE='completion batch identity and accounting immutable';
    END IF;
    -- A send cannot consume the result reserve. Counters never reset on rollover.
    IF clock_timestamp() >= OLD.expires_at - make_interval(secs=>OLD.result_reserve_seconds) THEN
      RAISE check_violation USING MESSAGE='completion batch send window expired';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO r FROM tutor_runs WHERE id=NEW.run_id FOR UPDATE;
  t:=clock_timestamp();
  IF NOT FOUND OR r.user_id<>NEW.user_id OR r.conversation_id<>NEW.conversation_id
     OR r.input_revision<>NEW.input_revision
     OR r.policy_json->>'execution_profile' IS DISTINCT FROM 'completion_driven_v1'
     OR r.policy_version IS DISTINCT FROM 'tutor_completion_driven_v1'
     OR r.policy_fingerprint IS DISTINCT FROM NEW.policy_fingerprint
     OR r.terminal_outcome IS NOT NULL OR r.cancelled_at IS NOT NULL OR r.superseded_by_run_id IS NOT NULL
     OR r.active_lease_owner_id IS DISTINCT FROM NEW.owner_id
     OR r.active_lease_generation<>NEW.owner_generation
     OR r.active_lease_expires_at IS NULL OR r.active_lease_expires_at<=t
     OR NEW.issued_at>t OR NEW.issued_at<t-interval '5 seconds'
     OR NEW.decision_count<>0 OR NEW.http_attempt_count<>0 THEN
    RAISE check_violation USING MESSAGE='completion batch current owner required';
  END IF;
  IF EXISTS (SELECT 1 FROM tutor_run_step_attempts WHERE run_id=NEW.run_id
      AND state IN ('prepared','dispatched','outcome_unknown')) THEN
    RAISE check_violation USING MESSAGE='completion unresolved attempt blocks successor';
  END IF;
  IF NEW.predecessor_batch_id IS NULL THEN
    IF NEW.batch_index<>1 THEN RAISE check_violation USING MESSAGE='completion batch root invalid'; END IF;
  ELSE
    SELECT * INTO p FROM tutor_run_execution_batches WHERE id=NEW.predecessor_batch_id FOR UPDATE;
    IF NOT FOUND OR p.run_id<>NEW.run_id OR NEW.batch_index<>p.batch_index+1
       OR p.input_revision<>NEW.input_revision OR p.policy_fingerprint<>NEW.policy_fingerprint THEN
      RAISE check_violation USING MESSAGE='completion batch predecessor invalid';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_tutor_run_step_attempt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  r tutor_runs%ROWTYPE;
  b tutor_run_execution_batches%ROWTYPE;
  p tutor_run_step_attempts%ROWTYPE;
  t timestamptz;
BEGIN
  IF TG_OP='DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE check_violation USING MESSAGE='completion step deletion denied';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF (to_jsonb(NEW)-ARRAY['state','dispatched_at','observable_http_count','http_batch_ids_json','result_type','result_json',
        'result_recorded_at','accepted_at','accepted_owner_id','accepted_owner_generation','acceptance_batch_id','diagnostic_code'])
       IS DISTINCT FROM
       (to_jsonb(OLD)-ARRAY['state','dispatched_at','observable_http_count','http_batch_ids_json','result_type','result_json',
        'result_recorded_at','accepted_at','accepted_owner_id','accepted_owner_generation','acceptance_batch_id','diagnostic_code']) THEN
      RAISE check_violation USING MESSAGE='completion step identity immutable';
    END IF;
    IF OLD.state IN ('accepted','rejected','not_sent','outcome_unknown') THEN
      IF NEW IS DISTINCT FROM OLD THEN RAISE check_violation USING MESSAGE='completion final result immutable'; END IF;
      RETURN NEW;
    END IF;
    IF OLD.result_json IS NOT NULL AND
       (NEW.result_json IS DISTINCT FROM OLD.result_json OR NEW.result_type IS DISTINCT FROM OLD.result_type
        OR NEW.result_recorded_at IS DISTINCT FROM OLD.result_recorded_at) THEN
      RAISE check_violation USING MESSAGE='completion recorded result immutable';
    END IF;
    IF OLD.dispatched_at IS NOT NULL AND NEW.dispatched_at IS DISTINCT FROM OLD.dispatched_at THEN
      RAISE check_violation USING MESSAGE='completion dispatch immutable';
    END IF;
    IF NOT ((OLD.state='prepared' AND NEW.state IN ('not_sent','dispatched'))
        OR (OLD.state='dispatched' AND NEW.state IN ('dispatched','result_recorded','outcome_unknown'))
        OR (OLD.state='result_recorded' AND NEW.state IN ('result_recorded','accepted','rejected'))) THEN
      RAISE check_violation USING MESSAGE='completion step transition invalid';
    END IF;
    IF NEW.observable_http_count NOT BETWEEN OLD.observable_http_count AND OLD.observable_http_count+1
       OR (NEW.observable_http_count<>OLD.observable_http_count AND
           (OLD.state NOT IN ('dispatched','result_recorded') OR NEW.state<>OLD.state))
       OR (NEW.observable_http_count=OLD.observable_http_count AND NEW.http_batch_ids_json<>OLD.http_batch_ids_json)
       OR (NEW.observable_http_count=OLD.observable_http_count+1 AND
           (NEW.http_batch_ids_json - (jsonb_array_length(NEW.http_batch_ids_json)-1))<>OLD.http_batch_ids_json) THEN
      RAISE check_violation USING MESSAGE='completion HTTP accounting invalid';
    END IF;
    -- Recording the original sent outcome is allowed after cancellation/takeover.
    -- This is private DATA only; it grants no business acceptance or retry.
    IF OLD.state='dispatched' AND NEW.state IN ('result_recorded','outcome_unknown') THEN RETURN NEW; END IF;
  END IF;
  SELECT * INTO r FROM tutor_runs WHERE id=NEW.run_id FOR UPDATE;
  t:=clock_timestamp();
  IF NOT FOUND OR r.user_id<>NEW.user_id OR r.conversation_id<>NEW.conversation_id
     OR r.input_revision<>NEW.input_revision
     OR r.policy_json->>'execution_profile' IS DISTINCT FROM 'completion_driven_v1'
     OR r.policy_version IS DISTINCT FROM 'tutor_completion_driven_v1'
     OR r.terminal_outcome IS NOT NULL OR r.cancelled_at IS NOT NULL OR r.superseded_by_run_id IS NOT NULL
     OR r.active_lease_expires_at IS NULL OR r.active_lease_expires_at<=t THEN
    RAISE check_violation USING MESSAGE='completion step current scope required';
  END IF;
  IF NEW.state='accepted' THEN
    SELECT * INTO b FROM tutor_run_execution_batches WHERE id=NEW.acceptance_batch_id FOR UPDATE;
    t:=clock_timestamp();
    IF NOT FOUND OR b.run_id<>r.id OR b.input_revision<>r.input_revision OR b.expires_at<=t
       OR b.owner_id IS DISTINCT FROM r.active_lease_owner_id OR b.owner_generation<>r.active_lease_generation
       OR NEW.accepted_owner_id IS DISTINCT FROM r.active_lease_owner_id
       OR NEW.accepted_owner_generation<>r.active_lease_generation OR r.active_lease_expires_at<=t THEN
      RAISE check_violation USING MESSAGE='completion fresh acceptance batch required';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.state IN ('not_sent','rejected') THEN RETURN NEW; END IF;
  IF TG_OP='UPDATE' AND NEW.observable_http_count<>OLD.observable_http_count THEN
    SELECT * INTO b FROM tutor_run_execution_batches
      WHERE id=(NEW.http_batch_ids_json->>-1)::uuid FOR UPDATE;
    t:=clock_timestamp();
    IF NOT FOUND OR b.run_id<>r.id OR b.input_revision<>r.input_revision
       OR b.owner_id IS DISTINCT FROM r.active_lease_owner_id OR b.owner_generation<>r.active_lease_generation
       OR b.expires_at<=t+make_interval(secs=>b.result_reserve_seconds) OR r.active_lease_expires_at<=t
       OR (OLD.state='dispatched' AND (NEW.owner_id IS DISTINCT FROM r.active_lease_owner_id
            OR NEW.owner_generation<>r.active_lease_generation OR b.id<>NEW.batch_id)) THEN
      RAISE check_violation USING MESSAGE='completion observable HTTP current batch required';
    END IF;
    UPDATE tutor_run_execution_batches SET http_attempt_count=http_attempt_count+1 WHERE id=b.id;
    RETURN NEW;
  END IF;
  IF NEW.owner_id IS DISTINCT FROM r.active_lease_owner_id OR NEW.owner_generation<>r.active_lease_generation THEN
    RAISE check_violation USING MESSAGE='completion dispatch owner replaced';
  END IF;
  SELECT * INTO b FROM tutor_run_execution_batches WHERE id=NEW.batch_id FOR UPDATE;
  t:=clock_timestamp();
  IF NOT FOUND OR b.run_id<>r.id OR b.input_revision<>r.input_revision
     OR b.owner_id<>NEW.owner_id OR b.owner_generation<>NEW.owner_generation
     OR b.expires_at<=t+make_interval(secs=>b.result_reserve_seconds) OR r.active_lease_expires_at<=t THEN
    RAISE check_violation USING MESSAGE='completion batch dispatch expired';
  END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.state<>'prepared' OR NEW.observable_http_count<>0 OR NEW.prepared_at>t
       OR NEW.prepared_at<t-interval '5 seconds' OR b.decision_count>=b.max_decisions
       OR b.http_attempt_count>=b.max_http_attempts
       OR NEW.capability_count_before<>r.capability_call_count OR NEW.effect_count_before<>r.effect_count THEN
      RAISE check_violation USING MESSAGE='completion preparation invalid';
    END IF;
    IF NEW.predecessor_attempt_id IS NULL THEN
      IF NEW.attempt_number<>1 OR NEW.decision_iteration<>r.model_call_count+1 THEN
        RAISE check_violation USING MESSAGE='completion step root invalid';
      END IF;
    ELSE
      SELECT * INTO p FROM tutor_run_step_attempts WHERE id=NEW.predecessor_attempt_id FOR UPDATE;
      IF NOT FOUND OR p.state<>'not_sent' OR p.run_id<>NEW.run_id OR p.step_key<>NEW.step_key
         OR p.kind<>NEW.kind OR p.decision_iteration<>NEW.decision_iteration
         OR NEW.attempt_number<>p.attempt_number+1 OR p.request_json<>NEW.request_json
         OR p.dependencies_json<>NEW.dependencies_json THEN
        RAISE check_violation USING MESSAGE='completion no-send predecessor required';
      END IF;
    END IF;
  ELSIF OLD.state='prepared' AND NEW.state='dispatched' THEN
    UPDATE tutor_run_execution_batches SET decision_count=decision_count+1 WHERE id=NEW.batch_id;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_tutor_completion_run_policy ON tutor_runs;
CREATE TRIGGER trg_tutor_completion_run_policy BEFORE UPDATE ON tutor_runs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_run_execution_batch();
DROP TRIGGER IF EXISTS trg_tutor_run_execution_batch ON tutor_run_execution_batches;
CREATE TRIGGER trg_tutor_run_execution_batch BEFORE INSERT OR UPDATE OR DELETE ON tutor_run_execution_batches
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_run_execution_batch();
DROP TRIGGER IF EXISTS trg_tutor_run_step_attempt ON tutor_run_step_attempts;
CREATE TRIGGER trg_tutor_run_step_attempt BEFORE INSERT OR UPDATE OR DELETE ON tutor_run_step_attempts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_run_step_attempt();
