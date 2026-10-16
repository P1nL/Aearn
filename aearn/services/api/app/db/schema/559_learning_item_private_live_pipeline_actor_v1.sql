-- C15: exact final524 PRIVATE pipeline actor branch, not output recovery authority.
-- Both generation and typed receipts retain all original content/control/source guards.
-- New native-live path: canonical namespace locks, full original goal/source, postwait current.
-- Old P6 and shared/public receivers stay unchanged. Caller owns the isolated transaction.
DO $fix559$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old559$
DECLARE control record; generation_facts record; version_facts record; scope_facts jsonb; scope_hash text; source_snapshot jsonb; expected_content text; expected_schema text;
BEGIN
  IF NEW.mode='synthetic' AND current_database() NOT IN ('aearn_b1b_fixture_20260930','aearn_b1d_sandbox_20261001') THEN
    RAISE check_violation USING MESSAGE='synthetic pipeline outside fixture';
  END IF;
  IF current_database()='aearn_b1d_sandbox_20261001' AND NOT EXISTS(
    SELECT 1 FROM users WHERE id=NEW.user_id AND display_name=('sandbox.p6.'||NEW.user_id::text) AND deleted_at IS NULL) THEN
    RAISE check_violation USING MESSAGE='synthetic sandbox actor required';
  END IF;
  SELECT * INTO control FROM tutor_item_supply_private_job_controls
    WHERE job_id=NEW.job_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR UPDATE;
  IF NOT FOUND OR control.lease_generation<>NEW.lease_generation OR control.state_version<>NEW.lease_state_version
    OR control.state NOT IN ('leased','generating','validating','reviewing','investigating','revising','simulating','admitting')
    OR control.lease_expires_at IS NULL OR control.lease_expires_at<=clock_timestamp() OR control.parent_deadline<=clock_timestamp() THEN
    RAISE check_violation USING MESSAGE='stale pipeline artifact lease';
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_private_generation_artifacts' THEN
    source_snapshot:=NEW.source_json;
    SELECT public_json,private_json,candidate_id INTO version_facts FROM tutor_item_supply_private_versions
      WHERE id=NEW.version_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id;
    SELECT snapshot_json,tutor_item_supply_private_scopes.scope_hash INTO scope_facts,scope_hash FROM tutor_item_supply_private_scopes
      WHERE id=NEW.scope_id AND user_id=NEW.user_id AND epoch=NEW.epoch;
    expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object(
      'item_key',source_snapshot->'public'->>'item_key','version',source_snapshot->'public'->>'version',
      'blueprint_hash',item_supply_internal.snapshot_hash(source_snapshot->'blueprint'),
      'public_hash',item_supply_internal.snapshot_hash(source_snapshot->'public'),
      'private_hash',item_supply_internal.snapshot_hash(source_snapshot->'private')));
    IF version_facts.candidate_id IS DISTINCT FROM NEW.candidate_id
      OR version_facts.public_json IS DISTINCT FROM source_snapshot->'public'
      OR version_facts.private_json IS DISTINCT FROM source_snapshot->'private'
      OR NEW.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(source_snapshot)
      OR NEW.content_hash IS DISTINCT FROM expected_content
      OR NEW.receipt_json->>'source_hash' IS DISTINCT FROM NEW.source_hash
      OR NEW.receipt_json->>'content_hash' IS DISTINCT FROM NEW.content_hash
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM scope_hash
      OR (NEW.mode='live' AND (
        NEW.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
        OR jsonb_typeof(NEW.receipt_json->'sources') IS DISTINCT FROM 'array'
        OR jsonb_array_length(NEW.receipt_json->'sources')=0
        OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.receipt_json->'sources') AS s
                  WHERE s->>'mode' IS DISTINCT FROM 'current_authority')))
      OR NEW.request_json->>'candidate_id' IS DISTINCT FROM NEW.receipt_json->>'candidate_id'
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM NEW.receipt_json->>'scope_hash'
      OR NEW.request_json->'blueprint' IS DISTINCT FROM source_snapshot->'blueprint'
      OR ((source_snapshot->'blueprint'->>'knowledge_key' IS DISTINCT FROM scope_facts->>'knowledge_key'
        OR source_snapshot->'blueprint'->>'language_id' IS DISTINCT FROM scope_facts->>'language_id'
        OR source_snapshot->'blueprint'->>'item_kind' IS DISTINCT FROM scope_facts->>'item_kind'
        OR source_snapshot->'blueprint'->>'purpose' IS DISTINCT FROM scope_facts->>'purpose')
       AND item_supply_internal.private_native_generation_goal_current(to_jsonb(NEW)) IS DISTINCT FROM true) THEN
      RAISE check_violation USING MESSAGE='pipeline source identity mismatch';
    END IF;
  ELSE
    SELECT source_hash,mode,candidate_id,version_id INTO generation_facts
      FROM tutor_item_supply_private_generation_artifacts
      WHERE id=NEW.generation_artifact_id AND user_id=NEW.user_id AND epoch=NEW.epoch
        AND scope_id=NEW.scope_id AND job_id=NEW.job_id AND version_id=NEW.version_id
        AND content_hash=NEW.content_hash;
    IF NOT FOUND OR generation_facts.mode IS DISTINCT FROM NEW.mode THEN
      RAISE check_violation USING MESSAGE='pipeline generation identity mismatch';
    END IF;
    expected_schema:=CASE NEW.artifact_kind WHEN 'validation' THEN 'candidate_validation_v2'
      WHEN 'blind_solve' THEN 'item_supply_blind_receipt_v2' WHEN 'review_bundle' THEN 'item_supply_review_bundle_v2'
      WHEN 'admission_evaluation' THEN 'item_supply_admission_evaluation_v2' END;
    IF NEW.schema_version IS DISTINCT FROM expected_schema
      OR COALESCE(NEW.payload_json->>'content_hash',NEW.payload_json->'binding'->>'content_hash') IS DISTINCT FROM NEW.content_hash
      OR COALESCE(NEW.payload_json->>'source_hash',NEW.payload_json->'binding'->>'source_hash') IS DISTINCT FROM generation_facts.source_hash
      OR (NEW.payload_json ? 'binding' AND (
        NEW.payload_json->'binding'->>'candidate_key' IS DISTINCT FROM generation_facts.candidate_id::text
        OR NEW.payload_json->'binding'->>'version_key' IS DISTINCT FROM generation_facts.version_id::text))
      OR (NEW.payload_json ? 'publication_enabled' AND NEW.payload_json->'publication_enabled'<>'false'::jsonb) THEN
      RAISE check_violation USING MESSAGE='pipeline receipt identity mismatch';
    END IF;
  END IF;
  RETURN NEW;
END $old559$;
 new_body constant text := $new559$
DECLARE control record; generation_facts record; version_facts record; scope_facts jsonb; scope_hash text; source_snapshot jsonb; expected_content text; expected_schema text;
  native_live boolean:=false;
  native_phase public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
  native_task public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
  native_ref jsonb; native_generation jsonb; native_stamp timestamptz;
BEGIN
  IF NEW.mode='synthetic' AND current_database() NOT IN ('aearn_b1b_fixture_20260930','aearn_b1d_sandbox_20261001') THEN
    RAISE check_violation USING MESSAGE='synthetic pipeline outside fixture';
  END IF;
  IF current_database()='aearn_b1d_sandbox_20261001' AND NOT EXISTS(
    SELECT 1 FROM users WHERE id=NEW.user_id AND display_name=('sandbox.p6.'||NEW.user_id::text) AND deleted_at IS NULL) THEN
    -- Recognition only. Old P6 actors never enter this additional branch.
    IF NEW.mode='live' AND NEW.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid
      AND NEW.epoch=1 AND NEW.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'::uuid
      AND TG_TABLE_NAME IN('tutor_item_supply_private_generation_artifacts','tutor_item_supply_private_pipeline_receipts')
      AND EXISTS(SELECT 1 FROM users WHERE id=NEW.user_id AND deleted_at IS NULL) THEN
      SELECT ph.* INTO native_phase FROM tutor_item_supply_private_persistent_pack_journal ph
        WHERE ph.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid
          AND ph.user_id=NEW.user_id AND ph.epoch=NEW.epoch AND ph.scope_id=NEW.scope_id AND ph.record_kind='phase'
          AND ph.operation_key='private.phase.'||NEW.job_id::text
          AND ph.payload_json->>'schema_version'='private_native_phase_v1'
          AND ph.payload_json->>'job_id'=NEW.job_id::text
          AND ph.payload_json->'ref'->>'mapping_receipt_id'='d8e34e01-3514-41a3-9bbd-55ee3e627134';
    END IF;
    IF native_phase.id IS NULL THEN
      RAISE check_violation USING MESSAGE='synthetic sandbox actor required';
    END IF;
    -- Canonical locks BEFORE the original control lock; no goal/source permission is cached.
    PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
    PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
      ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
      WHERE s.id=NEW.scope_id AND s.user_id=NEW.user_id AND s.epoch=NEW.epoch
      FOR SHARE OF s,p;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='559 current original native scope/active plan required'; END IF;
    SELECT task.* INTO native_task FROM tutor_item_supply_private_persistent_pack_journal task
      WHERE task.id=native_phase.pack_task_id AND task.pack_task_id=task.id AND task.record_kind='task'
        AND task.user_id=NEW.user_id AND task.epoch=NEW.epoch AND task.scope_id=NEW.scope_id FOR SHARE;
    native_ref:=native_phase.payload_json->'ref';
    IF native_task.id IS NULL OR native_task.payload_json->>'enhancement' IS DISTINCT FROM 'prefer_private'
      OR native_task.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
      OR (native_ref->>'pack_task_id',native_ref->>'user_id',native_ref->>'epoch',native_ref->>'scope_id') IS DISTINCT FROM
        (native_task.id::text,NEW.user_id::text,NEW.epoch::text,NEW.scope_id::text)
      OR (native_phase.payload_json->>'root_id',native_phase.payload_json->>'job_id',native_phase.payload_json->>'slot_id',
          native_phase.payload_json->>'business_item_id',native_phase.payload_json->>'goal_scope_id') IS DISTINCT FROM
        (native_ref->>'root_id',native_phase.payload_json->'lease'->>'job_id',native_ref->>'slot_id',
          native_ref->>'business_item_id',native_ref->>'goal_scope_id')
      OR (native_phase.payload_json->'lease'->>'visibility',native_phase.payload_json->'lease'->>'owner_id',
          native_phase.payload_json->'lease'->>'owner_epoch') IS DISTINCT FROM ('private',NEW.user_id::text,NEW.epoch::text)
      OR native_ref->>'root_id' IS DISTINCT FROM 'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
      OR jsonb_array_length(native_task.payload_json->'slots') IS DISTINCT FROM 5
      OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(native_task.payload_json->'slots') member
        WHERE member->>'slot_id'=native_ref->>'slot_id' AND member->>'logical_item_id'=native_ref->>'business_item_id'
          AND CASE WHEN member->>'slot' IN('practice-1','practice-2') THEN 'practice'
            WHEN member->>'slot' IN('assessment-1','assessment-2') THEN 'assessment'
            WHEN member->>'slot'='guided-remediation' THEN 'remediation' END=native_ref->>'slot') THEN
      RAISE check_violation USING MESSAGE='559 exact original native task/five-slot/phase namespace required';
    END IF;
    PERFORM 1 FROM tutor_item_supply_private_budget_roots root JOIN tutor_item_supply_private_jobs job
      ON job.root_id=root.id AND job.user_id=root.user_id AND job.epoch=root.epoch AND job.scope_id=root.scope_id
      WHERE root.id=(native_ref->>'root_id')::uuid AND root.user_id=NEW.user_id AND root.epoch=NEW.epoch
        AND root.scope_id=NEW.scope_id AND job.id=NEW.job_id FOR SHARE OF root,job;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='559 same original native canonical root/job required'; END IF;
    native_live:=true; -- Still requires the complete original content/source and final current fences.
  END IF;
  SELECT * INTO control FROM tutor_item_supply_private_job_controls
    WHERE job_id=NEW.job_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR UPDATE;
  IF NOT FOUND OR control.lease_generation<>NEW.lease_generation OR control.state_version<>NEW.lease_state_version
    OR control.state NOT IN ('leased','generating','validating','reviewing','investigating','revising','simulating','admitting')
    OR control.lease_expires_at IS NULL OR control.lease_expires_at<=clock_timestamp() OR control.parent_deadline<=clock_timestamp() THEN
    RAISE check_violation USING MESSAGE='stale pipeline artifact lease';
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_private_generation_artifacts' THEN
    source_snapshot:=NEW.source_json;
    SELECT public_json,private_json,candidate_id INTO version_facts FROM tutor_item_supply_private_versions
      WHERE id=NEW.version_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id;
    SELECT snapshot_json,tutor_item_supply_private_scopes.scope_hash INTO scope_facts,scope_hash FROM tutor_item_supply_private_scopes
      WHERE id=NEW.scope_id AND user_id=NEW.user_id AND epoch=NEW.epoch;
    expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object(
      'item_key',source_snapshot->'public'->>'item_key','version',source_snapshot->'public'->>'version',
      'blueprint_hash',item_supply_internal.snapshot_hash(source_snapshot->'blueprint'),
      'public_hash',item_supply_internal.snapshot_hash(source_snapshot->'public'),
      'private_hash',item_supply_internal.snapshot_hash(source_snapshot->'private')));
    IF version_facts.candidate_id IS DISTINCT FROM NEW.candidate_id
      OR version_facts.public_json IS DISTINCT FROM source_snapshot->'public'
      OR version_facts.private_json IS DISTINCT FROM source_snapshot->'private'
      OR NEW.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(source_snapshot)
      OR NEW.content_hash IS DISTINCT FROM expected_content
      OR NEW.receipt_json->>'source_hash' IS DISTINCT FROM NEW.source_hash
      OR NEW.receipt_json->>'content_hash' IS DISTINCT FROM NEW.content_hash
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM scope_hash
      OR (NEW.mode='live' AND (
        NEW.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
        OR jsonb_typeof(NEW.receipt_json->'sources') IS DISTINCT FROM 'array'
        OR jsonb_array_length(NEW.receipt_json->'sources')=0
        OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.receipt_json->'sources') AS s
                  WHERE s->>'mode' IS DISTINCT FROM 'current_authority')))
      OR NEW.request_json->>'candidate_id' IS DISTINCT FROM NEW.receipt_json->>'candidate_id'
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM NEW.receipt_json->>'scope_hash'
      OR NEW.request_json->'blueprint' IS DISTINCT FROM source_snapshot->'blueprint'
      OR ((source_snapshot->'blueprint'->>'knowledge_key' IS DISTINCT FROM scope_facts->>'knowledge_key'
        OR source_snapshot->'blueprint'->>'language_id' IS DISTINCT FROM scope_facts->>'language_id'
        OR source_snapshot->'blueprint'->>'item_kind' IS DISTINCT FROM scope_facts->>'item_kind'
        OR source_snapshot->'blueprint'->>'purpose' IS DISTINCT FROM scope_facts->>'purpose')
       AND item_supply_internal.private_native_generation_goal_current(to_jsonb(NEW)) IS DISTINCT FROM true) THEN
      RAISE check_violation USING MESSAGE='pipeline source identity mismatch';
    END IF;
    IF native_live AND item_supply_internal.private_native_generation_goal_current(to_jsonb(NEW)) IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='559 current original native generation goal/source required';
    END IF;
  ELSE
    SELECT source_hash,mode,candidate_id,version_id INTO generation_facts
      FROM tutor_item_supply_private_generation_artifacts
      WHERE id=NEW.generation_artifact_id AND user_id=NEW.user_id AND epoch=NEW.epoch
        AND scope_id=NEW.scope_id AND job_id=NEW.job_id AND version_id=NEW.version_id
        AND content_hash=NEW.content_hash;
    IF NOT FOUND OR generation_facts.mode IS DISTINCT FROM NEW.mode THEN
      RAISE check_violation USING MESSAGE='pipeline generation identity mismatch';
    END IF;
    IF native_live THEN
      -- Full JSON from the already identity-matched immutable generation, never the receipt's self-report.
      SELECT to_jsonb(generation) INTO native_generation FROM tutor_item_supply_private_generation_artifacts generation
        WHERE generation.id=NEW.generation_artifact_id AND generation.user_id=NEW.user_id AND generation.epoch=NEW.epoch
          AND generation.scope_id=NEW.scope_id AND generation.job_id=NEW.job_id AND generation.version_id=NEW.version_id
          AND generation.content_hash=NEW.content_hash AND generation.mode=NEW.mode;
      IF native_generation IS NULL OR item_supply_internal.private_native_generation_goal_current(native_generation) IS DISTINCT FROM true THEN
        RAISE check_violation USING MESSAGE='559 current original native receipt generation goal/source required';
      END IF;
    END IF;
    expected_schema:=CASE NEW.artifact_kind WHEN 'validation' THEN 'candidate_validation_v2'
      WHEN 'blind_solve' THEN 'item_supply_blind_receipt_v2' WHEN 'review_bundle' THEN 'item_supply_review_bundle_v2'
      WHEN 'admission_evaluation' THEN 'item_supply_admission_evaluation_v2' END;
    IF NEW.schema_version IS DISTINCT FROM expected_schema
      OR COALESCE(NEW.payload_json->>'content_hash',NEW.payload_json->'binding'->>'content_hash') IS DISTINCT FROM NEW.content_hash
      OR COALESCE(NEW.payload_json->>'source_hash',NEW.payload_json->'binding'->>'source_hash') IS DISTINCT FROM generation_facts.source_hash
      OR (NEW.payload_json ? 'binding' AND (
        NEW.payload_json->'binding'->>'candidate_key' IS DISTINCT FROM generation_facts.candidate_id::text
        OR NEW.payload_json->'binding'->>'version_key' IS DISTINCT FROM generation_facts.version_id::text))
      OR (NEW.payload_json ? 'publication_enabled' AND NEW.payload_json->'publication_enabled'<>'false'::jsonb) THEN
      RAISE check_violation USING MESSAGE='pipeline receipt identity mismatch';
    END IF;
  END IF;
  IF native_live THEN
    -- Full goal/source locks can wait. Re-read original phase/control currency AFTER them.
    IF item_supply_internal.private_pack_slot_current(native_phase.pack_task_id,(native_ref->>'slot_id')::uuid,
      (native_ref->>'business_item_id')::uuid,(native_ref->>'root_id')::uuid,
      NEW.user_id,NEW.epoch,NEW.scope_id,NEW.job_id) IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='559 postwait original native slot/phase/lease required';
    END IF;
    SELECT * INTO control FROM tutor_item_supply_private_job_controls
      WHERE job_id=NEW.job_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR UPDATE;
    native_stamp:=clock_timestamp();
    IF NOT FOUND OR control.lease_generation IS DISTINCT FROM NEW.lease_generation
      OR control.state_version IS DISTINCT FROM NEW.lease_state_version
      OR control.state NOT IN ('leased','generating','validating','reviewing','investigating','revising','simulating','admitting')
      OR control.lease_expires_at IS NULL OR control.parent_deadline IS NULL
      OR control.lease_expires_at<=native_stamp OR control.parent_deadline<=native_stamp
      OR (native_phase.payload_json->>'valid_until')::timestamptz IS NULL
      OR (native_phase.payload_json->>'valid_until')::timestamptz<=native_stamp THEN
      RAISE check_violation USING MESSAGE='559 postwait native generation/state-version or deadline stale';
    END IF;
  END IF;
  RETURN NEW;
END $new559$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='559 original isolated writable transaction required'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang
 WHERE p.oid=pg_catalog.to_regprocedure('public.enforce_item_supply_pipeline_artifact()');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'public'::regnamespace
  OR actual.proname IS DISTINCT FROM 'enforce_item_supply_pipeline_artifact'
  OR actual.lanname IS DISTINCT FROM 'plpgsql' OR actual.prokind<>'f'
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype
  OR actual.pronargs<>0 OR actual.proargtypes IS DISTINCT FROM ''::oidvector OR actual.proargnames IS NOT NULL
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='559 original pipeline receiver identity/attributes changed'; END IF;
 -- Exact old/new body only, after every identity/attribute/owner/ACL guard.
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='559 original final524 pipeline receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='559 original pipeline receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.*,l.lanname INTO verified FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='559 pipeline receiver metadata/OID/owner/ACL or body changed'; END IF;
END $fix559$;
