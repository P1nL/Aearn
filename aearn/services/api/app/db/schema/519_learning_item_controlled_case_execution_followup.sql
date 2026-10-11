-- STAGED/REGISTERED ONLY. Explicit execution2; no consumed execution is replayed.
-- Exact existing CHECK name was read by Main from the installed sandbox schema.
-- Preserve UNIQUE, old rows, historical anchors, all other constraints and guards.
ALTER TABLE tutor_item_supply_shared_controlled_case_executions
 DROP CONSTRAINT IF EXISTS tutor_item_supply_shared_controlled_cas_authorization_key_check;
ALTER TABLE tutor_item_supply_shared_controlled_case_executions
 ADD CONSTRAINT tutor_item_supply_shared_controlled_cas_authorization_key_check
 CHECK(authorization_key IN
   ('controlled-v3-same-case-execution-20261011-1','controlled-v3-same-case-execution-20261011-2'));

-- Exact 518 insert guard, changing only the closed authorization-key predicate.
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_controlled_case_execution_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE job_row tutor_item_supply_shared_jobs%ROWTYPE;
 control_row tutor_item_supply_shared_job_controls%ROWTYPE;
 profile_row tutor_item_supply_parameter_profiles%ROWTYPE;
 batch_row tutor_item_supply_development_model_accounting_batches%ROWTYPE;
 mapping_row tutor_item_supply_development_model_accounting_jobs%ROWTYPE;
 p jsonb:=NEW.payload_json; snapshot jsonb; stamp timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='controlled execution B1d only'; END IF;
 SELECT * INTO job_row FROM tutor_item_supply_shared_jobs jj WHERE jj.id=NEW.job_id;
 SELECT * INTO control_row FROM tutor_item_supply_shared_job_controls cc WHERE cc.job_id=NEW.job_id FOR UPDATE;
 SELECT * INTO profile_row FROM tutor_item_supply_parameter_profiles pp WHERE pp.id=control_row.profile_id;
 SELECT * INTO batch_row FROM tutor_item_supply_development_model_accounting_batches bb WHERE bb.id=NEW.batch_id FOR SHARE;
 SELECT * INTO mapping_row FROM tutor_item_supply_development_model_accounting_jobs mm WHERE mm.job_id=NEW.job_id FOR SHARE;
 snapshot:=CASE WHEN control_row.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN control_row.profile_snapshot_json->'profile' ELSE control_row.profile_snapshot_json END;
 stamp:=clock_timestamp();
 IF job_row.id IS NULL OR control_row.id IS NULL OR profile_row.id IS NULL OR batch_row.id IS NULL OR mapping_row.job_id IS NULL
   OR (NEW.authorization_key IS NULL OR NEW.authorization_key NOT IN
     ('controlled-v3-same-case-execution-20261011-1','controlled-v3-same-case-execution-20261011-2'))
   OR NEW.case_key IS DISTINCT FROM 'kc-multiscenario-repair-constant-generalization-v3'
   OR NEW.mode IS DISTINCT FROM 'controlled_execution_data_only' OR NEW.publication_enabled IS DISTINCT FROM false OR NEW.admission_eligible IS DISTINCT FROM false
   OR NEW.original_case_job_id IS DISTINCT FROM 'b8041728-d460-4ce2-ba29-47cbebd7b861'::uuid
   OR NEW.prior_failed_job_id IS DISTINCT FROM '670a94d4-605a-4a39-81f7-8fe424a6b620'::uuid
   OR item_supply_internal.controlled_case_execution_history_matches(NEW.root_id,NEW.original_case_job_id,NEW.prior_failed_job_id,NEW.context_hash) IS DISTINCT FROM true
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_controlled_counterexample_preparations op
     WHERE op.id=NEW.original_case_preparation_id AND op.job_id=NEW.original_case_job_id AND op.root_id=NEW.root_id AND op.payload_json->'context'=p->'context')
   OR job_row.root_id IS DISTINCT FROM NEW.root_id OR job_row.parent_job_id IS NOT NULL
   OR job_row.id IN (NEW.original_case_job_id,NEW.prior_failed_job_id)
   OR control_row.state IS DISTINCT FROM 'leased' OR control_row.breaker_open IS DISTINCT FROM false
   OR control_row.attempt_count IS DISTINCT FROM 1 OR control_row.lease_generation IS DISTINCT FROM 1
   OR control_row.lease_owner IS DISTINCT FROM NEW.lease_owner OR control_row.lease_generation IS DISTINCT FROM NEW.lease_generation
   OR control_row.state_version::bigint IS DISTINCT FROM NEW.lease_state_version
   OR control_row.lease_expires_at IS NULL OR control_row.lease_expires_at<=stamp OR control_row.parent_deadline<=stamp
   OR NEW.valid_until<=stamp OR NEW.valid_until>control_row.lease_expires_at OR NEW.valid_until>control_row.parent_deadline
   OR NEW.valid_until>batch_row.valid_until OR batch_row.started_at>stamp OR batch_row.valid_until<=stamp
   OR batch_row.authorization_key IS DISTINCT FROM 'development-unlimited-model-calls-20261010'
   OR batch_row.mode IS DISTINCT FROM 'accounting_only' OR batch_row.cumulative_caps_enforced IS DISTINCT FROM false
   OR batch_row.provider_key IS DISTINCT FROM 'deepseek' OR batch_row.model IS DISTINCT FROM 'deepseek-flash'
   OR mapping_row.batch_id IS DISTINCT FROM NEW.batch_id OR batch_row.root_id IS DISTINCT FROM NEW.root_id
   OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_owner IS DISTINCT FROM NEW.lease_owner
   OR mapping_row.lease_generation IS DISTINCT FROM NEW.lease_generation OR mapping_row.lease_state_version::bigint IS DISTINCT FROM NEW.lease_state_version
   OR mapping_row.profile_hash IS DISTINCT FROM NEW.profile_hash OR mapping_row.parent_deadline IS DISTINCT FROM control_row.parent_deadline
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_development_model_accounting_jobs mx
     WHERE mx.job_id=NEW.job_id AND mx.xmin::text::bigint<>(txid_current()%4294967296))
   OR profile_row.profile_hash IS DISTINCT FROM NEW.profile_hash OR snapshot->>'profile_hash' IS DISTINCT FROM NEW.profile_hash
   OR snapshot->>'profile_key_hash' IS DISTINCT FROM profile_row.profile_key_hash
   OR profile_row.profile_json->'profile_key'->>'provider' IS DISTINCT FROM 'deepseek'
   OR profile_row.profile_json->'profile_key'->>'model_version' IS DISTINCT FROM 'deepseek-flash'
   OR (snapshot->>'parent_deadline_at')::timestamptz IS DISTINCT FROM control_row.parent_deadline
   OR NEW.valid_until>(snapshot->>'parent_deadline_at')::timestamptz
   OR p->>'schema_version' IS DISTINCT FROM 'controlled_case_execution_authorization_v1'
   OR NOT item_supply_internal.snapshot_keys(p,ARRAY['schema_version','execution_id','authorization_key','case_key','context','context_hash','root_id','candidate_id','batch_id','original_case_preparation_id','original_case_job_id','prior_failed_job_id','lease','profile_hash','deadline_at','publication_enabled','admission_eligible'])
   OR p->>'execution_id' IS DISTINCT FROM NEW.id::text OR p->>'authorization_key' IS DISTINCT FROM NEW.authorization_key
   OR p->>'case_key' IS DISTINCT FROM NEW.case_key OR p->>'context_hash' IS DISTINCT FROM NEW.context_hash
   OR item_supply_internal.snapshot_hash(p->'context') IS DISTINCT FROM NEW.context_hash
   OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text OR p->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
   OR p->>'batch_id' IS DISTINCT FROM NEW.batch_id::text OR p->>'original_case_preparation_id' IS DISTINCT FROM NEW.original_case_preparation_id::text
   OR p->>'original_case_job_id' IS DISTINCT FROM NEW.original_case_job_id::text OR p->>'prior_failed_job_id' IS DISTINCT FROM NEW.prior_failed_job_id::text
   OR p->>'profile_hash' IS DISTINCT FROM NEW.profile_hash OR (p->>'deadline_at')::timestamptz IS DISTINCT FROM NEW.valid_until
   OR p->'lease'->'profile' IS DISTINCT FROM snapshot OR p->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
   OR p->'lease'->>'lease_owner' IS DISTINCT FROM NEW.lease_owner OR p->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
   OR p->'lease'->>'state_version' IS DISTINCT FROM NEW.lease_state_version::text
   OR (p->'lease'->>'expires_at')::timestamptz IS DISTINCT FROM control_row.lease_expires_at
   OR (p->'lease'->>'parent_deadline')::timestamptz IS DISTINCT FROM control_row.parent_deadline
   OR p->'lease'->>'visibility' IS DISTINCT FROM 'public' OR p->'lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
   OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR p->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations rr WHERE rr.job_id=NEW.job_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.job_id=NEW.job_id OR aa.candidate_id=NEW.candidate_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints ck WHERE ck.job_id=NEW.job_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_controlled_counterexample_preparations cp WHERE cp.job_id=NEW.job_id OR cp.candidate_id=NEW.candidate_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_controlled_execution_preparations cp WHERE cp.job_id=NEW.job_id OR cp.candidate_id=NEW.candidate_id) THEN
   RAISE check_violation USING MESSAGE='controlled execution requires exact current fresh original job/history/profile/batch';
 END IF;
 IF clock_timestamp()>=NEW.valid_until THEN RAISE check_violation USING MESSAGE='controlled execution operation deadline expired'; END IF;
 RETURN NEW;
END $$;

-- Exact 518 preparation-scope guard; only the closed authorization-key predicate changes.
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_controlled_execution_scope_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE execution_row tutor_item_supply_shared_controlled_case_executions%ROWTYPE;
 control_row tutor_item_supply_shared_job_controls%ROWTYPE;
 mapping_row tutor_item_supply_development_model_accounting_jobs%ROWTYPE;
 batch_row tutor_item_supply_development_model_accounting_batches%ROWTYPE;
 same_transaction boolean; stamp timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='controlled execution B1d only'; END IF;
 SELECT * INTO execution_row FROM tutor_item_supply_shared_controlled_case_executions ee WHERE ee.id=NEW.execution_id FOR SHARE;
 SELECT * INTO control_row FROM tutor_item_supply_shared_job_controls cc WHERE cc.job_id=NEW.job_id FOR SHARE;
 SELECT * INTO mapping_row FROM tutor_item_supply_development_model_accounting_jobs mm WHERE mm.job_id=NEW.job_id FOR SHARE;
 SELECT * INTO batch_row FROM tutor_item_supply_development_model_accounting_batches bb WHERE bb.id=execution_row.batch_id FOR SHARE;
 SELECT ee.xmin::text::bigint=(txid_current()%4294967296) INTO same_transaction
   FROM tutor_item_supply_shared_controlled_case_executions ee WHERE ee.id=NEW.execution_id;
 stamp:=clock_timestamp();
 IF execution_row.id IS NULL OR control_row.id IS NULL OR mapping_row.job_id IS NULL OR batch_row.id IS NULL
   OR same_transaction IS DISTINCT FROM false
   OR execution_row.root_id IS DISTINCT FROM NEW.root_id OR execution_row.job_id IS DISTINCT FROM NEW.job_id
   OR execution_row.candidate_id IS DISTINCT FROM NEW.candidate_id OR execution_row.case_key IS DISTINCT FROM NEW.experiment_key
   OR execution_row.context_hash IS DISTINCT FROM NEW.payload_json->>'context_hash'
   OR execution_row.payload_json->'context' IS DISTINCT FROM NEW.payload_json->'context'
   OR execution_row.payload_json->'lease' IS DISTINCT FROM NEW.payload_json->'lease'
   OR execution_row.lease_owner IS DISTINCT FROM NEW.lease_owner OR execution_row.lease_generation IS DISTINCT FROM NEW.lease_generation
   OR execution_row.lease_state_version IS DISTINCT FROM NEW.lease_state_version
   OR execution_row.valid_until<NEW.valid_until OR execution_row.valid_until<=stamp
   OR (execution_row.authorization_key IS NULL OR execution_row.authorization_key NOT IN
     ('controlled-v3-same-case-execution-20261011-1','controlled-v3-same-case-execution-20261011-2'))
   OR execution_row.publication_enabled IS DISTINCT FROM false OR execution_row.admission_eligible IS DISTINCT FROM false
   OR mapping_row.batch_id IS DISTINCT FROM execution_row.batch_id OR batch_row.root_id IS DISTINCT FROM NEW.root_id
   OR batch_row.valid_until<NEW.valid_until OR batch_row.valid_until<=stamp
   OR batch_row.authorization_key IS DISTINCT FROM 'development-unlimited-model-calls-20261010'
   OR batch_row.provider_key IS DISTINCT FROM 'deepseek' OR batch_row.model IS DISTINCT FROM 'deepseek-flash'
   OR control_row.state IS DISTINCT FROM 'leased' OR control_row.breaker_open IS DISTINCT FROM false
   OR control_row.attempt_count IS DISTINCT FROM 1 OR control_row.lease_owner IS DISTINCT FROM NEW.lease_owner
   OR control_row.lease_generation IS DISTINCT FROM NEW.lease_generation OR control_row.state_version::bigint IS DISTINCT FROM NEW.lease_state_version
   OR control_row.lease_expires_at IS NULL OR control_row.lease_expires_at<=stamp OR control_row.parent_deadline<=stamp
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_controlled_counterexample_preparations cp
       WHERE cp.job_id=NEW.job_id OR cp.candidate_id=NEW.candidate_id) THEN
   RAISE check_violation USING MESSAGE='controlled preparation requires committed current original execution scope';
 END IF;
 RETURN NEW;
END $$;



