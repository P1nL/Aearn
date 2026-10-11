-- STAGED/REGISTERED ONLY. Explicit same case, new server-issued execution.
-- Legacy 511--517 tables, UNIQUE constraints, guards and historical DATA are unchanged.
-- The only existing function extended is the DENY-only ancestry hold predicate.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_controlled_case_executions (
 id uuid PRIMARY KEY,
 authorization_key text NOT NULL UNIQUE CHECK(authorization_key='controlled-v3-same-case-execution-20261011-1'),
 case_key text NOT NULL CHECK(case_key='kc-multiscenario-repair-constant-generalization-v3'),
 context_hash text NOT NULL CHECK(context_hash ~ '^[0-9a-f]{64}$'),
 root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
 job_id uuid NOT NULL UNIQUE, candidate_id uuid NOT NULL UNIQUE,
 batch_id uuid NOT NULL REFERENCES tutor_item_supply_development_model_accounting_batches(id) ON DELETE RESTRICT,
 original_case_preparation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_controlled_counterexample_preparations(id) ON DELETE RESTRICT,
 original_case_job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT,
 prior_failed_job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT,
 lease_owner text NOT NULL, lease_generation integer NOT NULL CHECK(lease_generation=1),
 lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
 profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=131072),
 snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 valid_until timestamptz NOT NULL,
 mode text NOT NULL DEFAULT 'controlled_execution_data_only' CHECK(mode='controlled_execution_data_only'),
 publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
 admission_eligible boolean NOT NULL DEFAULT false CHECK(admission_eligible=false),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(id,root_id,job_id,candidate_id),
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_controlled_execution_preparations (
 id uuid PRIMARY KEY, execution_id uuid NOT NULL UNIQUE,
 experiment_key text NOT NULL CHECK(experiment_key='kc-multiscenario-repair-constant-generalization-v3'),
 root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
 job_id uuid NOT NULL UNIQUE, candidate_id uuid NOT NULL UNIQUE,
 lease_owner text NOT NULL, lease_generation integer NOT NULL CHECK(lease_generation>0),
 lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=524288),
 snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 valid_until timestamptz NOT NULL, mode text NOT NULL DEFAULT 'controlled_data_only' CHECK(mode='controlled_data_only'),
 publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
 admission_eligible boolean NOT NULL DEFAULT false CHECK(admission_eligible=false),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(id,root_id,job_id,candidate_id),
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
 FOREIGN KEY(execution_id,root_id,job_id,candidate_id)
   REFERENCES tutor_item_supply_shared_controlled_case_executions(id,root_id,job_id,candidate_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_controlled_execution_receipts (
 id uuid PRIMARY KEY, preparation_id uuid NOT NULL UNIQUE, root_id uuid NOT NULL,
 job_id uuid NOT NULL, candidate_id uuid NOT NULL, reservation_id uuid NOT NULL UNIQUE,
 settlement_id uuid NOT NULL REFERENCES tutor_item_supply_shared_runtime_settlements(id) ON DELETE RESTRICT,
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576),
 snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 mode text NOT NULL DEFAULT 'controlled_observed_data_only' CHECK(mode='controlled_observed_data_only'),
 publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
 admission_eligible boolean NOT NULL DEFAULT false CHECK(admission_eligible=false),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(preparation_id,root_id,job_id,candidate_id)
   REFERENCES tutor_item_supply_shared_controlled_execution_preparations(id,root_id,job_id,candidate_id) ON DELETE RESTRICT,
 FOREIGN KEY(reservation_id,job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT
);


-- This historical projection is DATA only. It never requires an old lease/source
-- grant to be live and never restores an old issuer or changes old UNKNOWN usage.
CREATE OR REPLACE FUNCTION item_supply_internal.controlled_case_execution_history_matches(
 operation_root uuid, original_job uuid, failed_job uuid, case_context_hash text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 SELECT current_database()='aearn_b1d_sandbox_20261001'
   AND operation_root='7d4b85ba-a0ec-4348-ac11-3401c6bded47'::uuid
   AND original_job='b8041728-d460-4ce2-ba29-47cbebd7b861'::uuid
   AND failed_job='670a94d4-605a-4a39-81f7-8fe424a6b620'::uuid
   AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_controlled_counterexample_preparations pp
     JOIN tutor_item_supply_shared_jobs pj ON pj.id=pp.job_id
     JOIN tutor_item_supply_shared_generation_artifacts ga ON ga.job_id=pp.job_id AND ga.candidate_id=pp.candidate_id
     JOIN tutor_item_supply_shared_review_investigation_receipts ir ON ir.generation_artifact_id=ga.id AND ir.job_id=pj.id
     JOIN tutor_item_supply_shared_runtime_settlements ss ON ss.id=ir.settlement_id AND ss.reservation_id=ir.reservation_id
     WHERE pj.id=original_job AND pj.root_id=operation_root AND pp.root_id=operation_root
       AND ga.id='43391bb6-cae6-41ba-8245-35245694c2cf'::uuid AND ga.root_id=operation_root
       AND ir.id='2b007994-9b07-420d-b2c5-9ae860826a7f'::uuid AND ir.root_id=operation_root
       AND pp.experiment_key='kc-multiscenario-repair-constant-generalization-v3'
       AND pp.payload_json->>'context_hash'=case_context_hash
       AND item_supply_internal.snapshot_hash(pp.payload_json->'context')=case_context_hash
       AND pp.payload_json->'context'->>'schema_version'='controlled_kc_counterexample_context_v3'
       AND pp.payload_json->'context'->>'experiment_key'=pp.experiment_key
       AND pp.publication_enabled=false AND pp.admission_eligible=false
       AND ir.publication_enabled=false AND ir.payload_json->'publication_enabled'='false'::jsonb
       AND ir.payload_json->'admission_eligible'='false'::jsonb AND ir.payload_json->'blockers_discharged'='false'::jsonb
       AND ir.payload_json->>'usage_state'='unknown' AND ss.usage_state='unknown'
       AND ir.payload_json->'observation'='null'::jsonb
       AND ir.payload_json->>'state'='investigation_pending_revision_owner'
       AND ir.payload_json->>'safe_reason'='investigation_analysis_pending_revision_owner'
       AND ir.payload_json->'report'->'run'->>'prompt_version'='native-shared-review-investigation-v2'
       AND ir.payload_json->'report'->'run'->>'max_output_tokens'='61440'
       AND CASE WHEN jsonb_typeof(ir.payload_json->'report'->'output'->'analyses')='array'
         THEN jsonb_array_length(ir.payload_json->'report'->'output'->'analyses')=4 ELSE false END
       AND item_supply_internal.controlled_counterexample_held(original_job)
       AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations rp WHERE rp.parent_artifact_id=ga.id)
       AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_lineage rl WHERE rl.parent_artifact_id=ga.id)
       AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_recheck_preparations rc WHERE rc.generation_artifact_id=ga.id)
       AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff WHERE ff.generation_artifact_id=ga.id)
       AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.generation_artifact_id=ga.id AND rr.artifact_kind='admission_evaluation')
       AND NOT EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe WHERE pe.version_id=ga.version_id))
   AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_jobs fj WHERE fj.id=failed_job AND fj.root_id=operation_root)
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations rr WHERE rr.job_id=failed_job)
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.job_id=failed_job)
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_controlled_counterexample_preparations cp WHERE cp.job_id=failed_job)
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_controlled_case_executions ce WHERE ce.job_id=failed_job)
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_controlled_execution_preparations cp WHERE cp.job_id=failed_job)
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.job_id=failed_job)
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cc WHERE cc.job_id=failed_job)
$$;

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
   OR NEW.authorization_key IS DISTINCT FROM 'controlled-v3-same-case-execution-20261011-1'
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
   OR execution_row.authorization_key IS DISTINCT FROM 'controlled-v3-same-case-execution-20261011-1'
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
-- Exact 515 case/source/request/envelope/usage guard, renamed for parallel tables only.
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_controlled_execution_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE preparation_row tutor_item_supply_shared_controlled_execution_preparations%ROWTYPE;
 control_row tutor_item_supply_shared_job_controls%ROWTYPE;
 reservation_row tutor_item_supply_shared_reservations%ROWTYPE;
 settlement_row tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 p jsonb; request_payload jsonb; context_payload jsonb; snapshot jsonb; binding jsonb; envelope jsonb; user_input jsonb; prompt_contract jsonb;
 amount_kind text; amount_value jsonb; same_transaction boolean;
 expected_context_schema text; expected_rule text; expected_seed jsonb; expected_wrong text; expected_program text; expected_blueprint text; expected_slot text:='practice-1';
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='controlled counterexample B1d only'; END IF;
 IF TG_TABLE_NAME='tutor_item_supply_shared_controlled_execution_preparations' THEN
   p:=NEW.payload_json;
   IF p->>'schema_version' IS DISTINCT FROM 'controlled_counterexample_preparation_v1'
     OR NOT item_supply_internal.snapshot_keys(p,ARRAY['schema_version','preparation_id','root_id','lease','request','request_hash','context','context_hash','rule_hash','sources','source_bindings_hash','producer_binding','evidence_policy_hash','deadline_at','publication_enabled','admission_eligible'])
     OR p->>'preparation_id' IS DISTINCT FROM NEW.id::text OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text THEN
     RAISE check_violation USING MESSAGE='closed controlled preparation required';
   END IF;
   request_payload:=p->'request'; context_payload:=p->'context';
   SELECT * INTO control_row FROM tutor_item_supply_shared_job_controls cc WHERE cc.job_id=NEW.job_id FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='controlled original job missing'; END IF;
   snapshot:=CASE WHEN control_row.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
     THEN control_row.profile_snapshot_json->'profile' ELSE control_row.profile_snapshot_json END;
   -- Exactly three approved experiment versions; old V1/V2 predicates remain exact.
   IF NEW.experiment_key='kc-rebinding-wrong-explanation-v1' THEN
     expected_context_schema:='controlled_kc_counterexample_context_v1';
     expected_rule:='kc_rebinding_wrong_explanation_v1'; expected_seed:='24'::jsonb;
     expected_wrong:='执行 price = 8 后，price 会自动恢复成先前的 6，当前 price 仍为 6；变量再次赋值不会改变当前绑定值。';
     expected_program:=E'price = 6\nqty = 3\ntotal = price * qty\nprice = 8\nreceipt = total + 1\nprint(total, receipt)';
     expected_blueprint:='finite.python-kc-binding-v1.practice-1.family-diagnose.s24';
   ELSIF NEW.experiment_key='kc-linked-name-refutation-wrong-rationale-v2' THEN
     expected_context_schema:='controlled_kc_counterexample_context_v2';
     expected_rule:='kc_linked_name_refutation_wrong_rationale_v2'; expected_seed:='0'::jsonb;
     expected_wrong:='对整数执行 saved = source 会建立两个名字的永久联动；source 从 4 重绑定到 9 后，saved 必须同步变为 9，程序实际输出 9 9。';
     expected_program:=E'source = 4\nsaved = source\nsource = 9\nprint(source, saved)';
     expected_blueprint:='finite.python-kc-binding-v1.practice-1.family-counterexample.s0';
   ELSIF NEW.experiment_key='kc-multiscenario-repair-constant-generalization-v3' THEN
     expected_context_schema:='controlled_kc_counterexample_context_v3';
     expected_rule:='kc_multiscenario_repair_constant_generalization_v3'; expected_seed:='0'::jsonb;
     expected_wrong:='入口x=3和8时，先保存old，再把x增加2；此后new=10与new=x*2在两个场景都等价，固定10同时满足new为更新后x两倍的约束。';
     expected_program:=E'old = x\nx = x + 2\nnew = x * 2';
     expected_blueprint:='finite.python-kc-binding-v1.assessment-1.family-repair.s0';
     expected_slot:='assessment-1';
   ELSE
     RAISE check_violation USING MESSAGE='closed controlled experiment version required';
   END IF;
   IF context_payload->>'schema_version' IS DISTINCT FROM expected_context_schema
     OR NOT item_supply_internal.snapshot_keys(context_payload,ARRAY['schema_version','experiment_key','rule_version','target','slot','seed','wrong_explanation','publication_enabled','admission_eligible'])
     OR context_payload->>'experiment_key' IS DISTINCT FROM NEW.experiment_key
     OR context_payload->>'rule_version' IS DISTINCT FROM expected_rule
     OR context_payload->>'target' IS DISTINCT FROM 'python-kc-binding-v1' OR context_payload->>'slot' IS DISTINCT FROM expected_slot
     OR context_payload->'seed' IS DISTINCT FROM expected_seed
     OR context_payload->>'wrong_explanation' IS DISTINCT FROM expected_wrong
     OR context_payload->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR context_payload->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
     OR p->>'context_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(context_payload)
     OR p->>'rule_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('rule',expected_rule,
       'field','/private/content/answer_explanation_markdown','program',expected_program,
       'wrong_explanation',context_payload->>'wrong_explanation'))
     OR request_payload->>'schema_version' IS DISTINCT FROM 'item_generation_request_v2'
     OR request_payload->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
     OR request_payload->'blueprint'->>'version' IS DISTINCT FROM 'finite-public-spec-v3'
     OR request_payload->'blueprint'->>'blueprint_key' IS DISTINCT FROM expected_blueprint
     OR request_payload->'public_template'->>'kind' IS DISTINCT FROM 'knowledge_check'
     OR (CASE WHEN expected_context_schema='controlled_kc_counterexample_context_v1'
         THEN position(expected_program in COALESCE(request_payload->'public_template'->'content'->>'prompt_markdown',''))>0
         ELSE (request_payload->'public_template'->'content'->>'response_kind'='single_choice'
           AND EXISTS(SELECT 1 FROM jsonb_array_elements(CASE
               WHEN jsonb_typeof(request_payload->'public_template'->'content'->'options')='array'
               THEN request_payload->'public_template'->'content'->'options' ELSE '[]'::jsonb END) option_row
             WHERE position(expected_program in COALESCE(option_row->>'label',''))>0)) END) IS DISTINCT FROM true
     OR request_payload->'demand_binding' IS DISTINCT FROM 'null'::jsonb
     OR request_payload->'profile' IS DISTINCT FROM snapshot OR p->'lease'->'profile' IS DISTINCT FROM snapshot
     OR p->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(request_payload)
     OR p->>'source_bindings_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'sources')
     OR jsonb_typeof(p->'sources') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'sources')<1
     OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'sources') src WHERE src->>'mode' IS DISTINCT FROM 'current_authority')
     OR request_payload->'limits'->'max_output_tokens' IS DISTINCT FROM '61440'::jsonb
     OR request_payload->'limits'->'max_input_bytes' IS DISTINCT FROM '131072'::jsonb
     OR control_row.state IS DISTINCT FROM 'leased' OR control_row.lease_owner IS DISTINCT FROM NEW.lease_owner
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_jobs sj WHERE sj.id=NEW.job_id AND sj.root_id=NEW.root_id)
     OR control_row.lease_generation IS DISTINCT FROM NEW.lease_generation OR control_row.state_version::bigint IS DISTINCT FROM NEW.lease_state_version
     OR p->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text OR p->'lease'->>'lease_owner' IS DISTINCT FROM NEW.lease_owner
     OR p->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text OR p->'lease'->>'state_version' IS DISTINCT FROM NEW.lease_state_version::text
     OR p->'lease'->>'visibility' IS DISTINCT FROM 'public' OR p->'lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
     OR (p->>'deadline_at')::timestamptz IS DISTINCT FROM NEW.valid_until
     OR NEW.valid_until>control_row.lease_expires_at OR NEW.valid_until>control_row.parent_deadline OR NEW.valid_until<=clock_timestamp()
     OR p->'producer_binding' IS DISTINCT FROM '["deepseek","deepseek-flash"]'::jsonb
     OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR p->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations rr WHERE rr.job_id=NEW.job_id)
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.job_id=NEW.job_id OR aa.candidate_id=NEW.candidate_id)
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='generating' AND cp.status='completed') THEN
     RAISE check_violation USING MESSAGE='controlled exact source/profile/context/lease required';
   END IF;
 ELSE
   SELECT * INTO preparation_row FROM tutor_item_supply_shared_controlled_execution_preparations pp WHERE pp.id=NEW.preparation_id FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='controlled original marker required'; END IF;
   SELECT pp.xmin::text::bigint=(txid_current() % 4294967296) INTO same_transaction
     FROM tutor_item_supply_shared_controlled_execution_preparations pp WHERE pp.id=NEW.preparation_id;
   IF same_transaction IS DISTINCT FROM false THEN RAISE check_violation USING MESSAGE='controlled committed marker required'; END IF;
   p:=preparation_row.payload_json; binding:=NEW.payload_json->'binding'; envelope:=NEW.payload_json->'actual_envelope';
   SELECT * INTO reservation_row FROM tutor_item_supply_shared_reservations rr WHERE rr.id=NEW.reservation_id FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='controlled original author reservation required'; END IF;
   SELECT * INTO settlement_row FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.id=NEW.settlement_id FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='controlled original settled usage required'; END IF;
   SELECT ss.xmin::text::bigint=(txid_current() % 4294967296) INTO same_transaction
     FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.id=NEW.settlement_id;
   IF same_transaction IS DISTINCT FROM false THEN RAISE check_violation USING MESSAGE='controlled committed settlement required'; END IF;
   SELECT * INTO control_row FROM tutor_item_supply_shared_job_controls cc WHERE cc.job_id=NEW.job_id FOR SHARE;
   IF NOT FOUND OR control_row.lease_expires_at<=clock_timestamp() OR preparation_row.valid_until<=clock_timestamp()
     OR control_row.lease_owner IS DISTINCT FROM preparation_row.lease_owner
     OR control_row.lease_generation IS DISTINCT FROM preparation_row.lease_generation
     OR control_row.state_version::bigint IS DISTINCT FROM preparation_row.lease_state_version THEN
     RAISE check_violation USING MESSAGE='controlled current original lease required';
   END IF;
   user_input:=(envelope->'messages'->1->>'content')::jsonb;
   -- Explicit const lives in the real author SYSTEM schema, while the original
   -- transport's base Source wire schema remains unchanged (no provider proxy).
   prompt_contract:=split_part(envelope->'messages'->0->>'content',E'\nAUTHORITATIVE OUTPUT JSON SCHEMA:\n',2)::jsonb;
   IF NEW.payload_json->>'schema_version' IS DISTINCT FROM 'controlled_counterexample_author_receipt_v1'
     OR NOT item_supply_internal.snapshot_keys(NEW.payload_json,ARRAY['schema_version','preparation_id','preparation_hash','request_hash','context_hash','lease','binding','actual_envelope','result','result_hash','reservation_id','settlement_id','usage_state','publication_enabled','admission_eligible'])
     OR NEW.payload_json->>'preparation_id' IS DISTINCT FROM NEW.preparation_id::text
     OR NEW.payload_json->>'preparation_hash' IS DISTINCT FROM preparation_row.snapshot_hash
     OR NEW.payload_json->>'request_hash' IS DISTINCT FROM p->>'request_hash' OR NEW.payload_json->>'context_hash' IS DISTINCT FROM p->>'context_hash'
     OR binding->>'schema_version' IS DISTINCT FROM 'controlled_author_input_binding_v1'
     OR NOT item_supply_internal.snapshot_keys(binding,ARRAY['schema_version','request_hash','context_hash','messages_hash','output_schema_hash','envelope_hash','input_bytes'])
     OR NOT item_supply_internal.snapshot_keys(envelope,ARRAY['messages','output_schema'])
     OR NOT item_supply_internal.snapshot_keys(NEW.payload_json->'result',ARRAY['state','source','receipt','safe_reason'])
     OR jsonb_typeof(envelope->'messages') IS DISTINCT FROM 'array' OR jsonb_array_length(envelope->'messages')<>2
     OR envelope->'messages'->0->>'role' IS DISTINCT FROM 'system' OR envelope->'messages'->1->>'role' IS DISTINCT FROM 'user'
     OR binding->>'request_hash' IS DISTINCT FROM p->>'request_hash' OR binding->>'context_hash' IS DISTINCT FROM p->>'context_hash'
     OR binding->>'messages_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(envelope->'messages')
     OR binding->>'output_schema_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(envelope->'output_schema')
     OR binding->>'envelope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(envelope)
     OR jsonb_typeof(binding->'input_bytes') IS DISTINCT FROM 'number' OR COALESCE((binding->>'input_bytes')::bigint,0) NOT BETWEEN 1 AND 131072
     OR user_input->'controlled_context'->>'context_hash' IS DISTINCT FROM p->>'context_hash'
     OR user_input->'controlled_context'->>'fixed_value' IS DISTINCT FROM p->'context'->>'wrong_explanation'
     OR prompt_contract->'$defs'->'LearningItemKnowledgeCheckPrivateV1'->'properties'->'answer_explanation_markdown'->>'const' IS DISTINCT FROM p->'context'->>'wrong_explanation'
     OR reservation_row.job_id IS DISTINCT FROM NEW.job_id OR reservation_row.root_id IS DISTINCT FROM NEW.root_id
     OR reservation_row.lease_generation IS DISTINCT FROM preparation_row.lease_generation
     OR reservation_row.reservation_key IS DISTINCT FROM 'gen.'||replace(NEW.candidate_id::text,'-','')
     OR settlement_row.reservation_id IS DISTINCT FROM NEW.reservation_id OR settlement_row.settlement_key IS DISTINCT FROM 'generation.'||replace(NEW.candidate_id::text,'-','')
     OR NEW.payload_json->>'reservation_id' IS DISTINCT FROM NEW.reservation_id::text OR NEW.payload_json->>'settlement_id' IS DISTINCT FROM NEW.settlement_id::text
     OR NEW.payload_json->>'usage_state' IS DISTINCT FROM settlement_row.usage_state
     OR (settlement_row.usage_state='unknown' AND (settlement_row.cost_amount IS NOT NULL OR settlement_row.receipt_hash IS NOT NULL
       OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlement_amounts aa WHERE aa.settlement_id=NEW.settlement_id)))
     OR (settlement_row.usage_state='known' AND settlement_row.receipt_hash IS DISTINCT FROM
       item_supply_internal.snapshot_hash(NEW.payload_json->'result'->'receipt'->'provider'))
     OR NEW.payload_json->'lease' IS DISTINCT FROM p->'lease'
     OR NEW.payload_json->>'result_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.payload_json->'result')
     OR NEW.payload_json->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR NEW.payload_json->'admission_eligible' IS DISTINCT FROM 'false'::jsonb THEN
     RAISE check_violation USING MESSAGE='controlled original envelope/result/settlement required';
   END IF;
   IF NEW.payload_json->'result'->>'state'='staged' AND (
      NEW.payload_json->'result'->'source'->'private'->'content'->>'answer_explanation_markdown' IS DISTINCT FROM p->'context'->>'wrong_explanation'
      OR NEW.payload_json->'result'->'receipt'->'sources' IS DISTINCT FROM p->'sources') THEN
     RAISE check_violation USING MESSAGE='controlled unchanged original seeded output required';
   END IF;
   FOR amount_kind,amount_value IN SELECT key,value FROM jsonb_each(jsonb_build_object('requests',1,'input_tokens',131072,'output_tokens',61440,
       'execution_seconds',0,'fetches',0,'candidates',1,'revision_rounds',0,'investigation_rounds',0)) LOOP
     IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts aa WHERE aa.reservation_namespace='shared'
         AND aa.reservation_id=NEW.reservation_id AND aa.resource_kind=amount_kind AND aa.reserved_amount=(amount_value::text)::bigint)
       OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts aa WHERE aa.reservation_namespace='shared'
         AND aa.reservation_id=NEW.reservation_id AND aa.resource_kind=amount_kind AND aa.reserved_amount<>(amount_value::text)::bigint) THEN
       RAISE check_violation USING MESSAGE='controlled exact original resource reservation required';
     END IF;
   END LOOP;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.controlled_counterexample_held(operation_job uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 WITH RECURSIVE ancestry AS (
   SELECT j.id,j.parent_job_id FROM tutor_item_supply_shared_jobs j WHERE j.id=operation_job
   UNION SELECT j.id,j.parent_job_id FROM tutor_item_supply_shared_jobs j JOIN ancestry aa ON j.id=aa.parent_job_id
 ) SELECT EXISTS(SELECT 1 FROM ancestry aa JOIN tutor_item_supply_shared_controlled_counterexample_preparations pp ON pp.job_id=aa.id)
   OR EXISTS(SELECT 1 FROM ancestry aa JOIN tutor_item_supply_shared_controlled_execution_preparations pp ON pp.job_id=aa.id)
$$;


REVOKE ALL ON FUNCTION item_supply_internal.controlled_case_execution_history_matches(uuid,uuid,uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_controlled_case_execution_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_controlled_execution_scope_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_controlled_execution_insert() FROM PUBLIC;

-- Original 511 generation binding/committed trace guard, parallel-only copy.
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_controlled_execution_generation_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE preparation_row tutor_item_supply_shared_controlled_execution_preparations%ROWTYPE;
 receipt_row tutor_item_supply_shared_controlled_execution_receipts%ROWTYPE;
 same_transaction boolean;
BEGIN
 SELECT * INTO preparation_row FROM tutor_item_supply_shared_controlled_execution_preparations pp
   WHERE pp.job_id=NEW.job_id OR pp.candidate_id=NEW.candidate_id FOR SHARE;
 IF FOUND THEN
   SELECT * INTO receipt_row FROM tutor_item_supply_shared_controlled_execution_receipts rr WHERE rr.preparation_id=preparation_row.id FOR SHARE;
   IF NOT FOUND OR receipt_row.job_id IS DISTINCT FROM NEW.job_id OR receipt_row.root_id IS DISTINCT FROM NEW.root_id
     OR receipt_row.candidate_id IS DISTINCT FROM NEW.candidate_id OR receipt_row.reservation_id IS DISTINCT FROM NEW.reservation_id
     OR receipt_row.payload_json->'result'->>'state' IS DISTINCT FROM 'staged'
     OR receipt_row.payload_json->'result'->'source' IS DISTINCT FROM NEW.source_json
     OR receipt_row.payload_json->'result'->'receipt' IS DISTINCT FROM NEW.receipt_json
     OR preparation_row.payload_json->'request' IS DISTINCT FROM NEW.request_json THEN
     RAISE check_violation USING MESSAGE='controlled parent requires immutable original author trace';
   END IF;
   SELECT rr.xmin::text::bigint=(txid_current() % 4294967296) INTO same_transaction
     FROM tutor_item_supply_shared_controlled_execution_receipts rr WHERE rr.id=receipt_row.id;
   IF same_transaction IS DISTINCT FROM false THEN RAISE check_violation USING MESSAGE='controlled committed trace required'; END IF;
 END IF;
 RETURN NEW;
END $$;

REVOKE ALL ON FUNCTION item_supply_internal.enforce_controlled_execution_generation_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS controlled_execution_generation_insert ON tutor_item_supply_shared_generation_artifacts;
CREATE TRIGGER controlled_execution_generation_insert BEFORE INSERT ON tutor_item_supply_shared_generation_artifacts
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_controlled_execution_generation_insert();

DROP TRIGGER IF EXISTS controlled_case_execution_insert ON tutor_item_supply_shared_controlled_case_executions;
CREATE TRIGGER controlled_case_execution_insert BEFORE INSERT ON tutor_item_supply_shared_controlled_case_executions
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_controlled_case_execution_insert();
DROP TRIGGER IF EXISTS controlled_execution_scope_insert ON tutor_item_supply_shared_controlled_execution_preparations;
CREATE TRIGGER controlled_execution_scope_insert BEFORE INSERT ON tutor_item_supply_shared_controlled_execution_preparations
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_controlled_execution_scope_insert();
DROP TRIGGER IF EXISTS controlled_execution_preparation_insert ON tutor_item_supply_shared_controlled_execution_preparations;
CREATE TRIGGER controlled_execution_preparation_insert BEFORE INSERT ON tutor_item_supply_shared_controlled_execution_preparations
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_controlled_execution_insert();
DROP TRIGGER IF EXISTS controlled_execution_receipt_insert ON tutor_item_supply_shared_controlled_execution_receipts;
CREATE TRIGGER controlled_execution_receipt_insert BEFORE INSERT ON tutor_item_supply_shared_controlled_execution_receipts
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_controlled_execution_insert();
DROP TRIGGER IF EXISTS controlled_case_execution_immutable ON tutor_item_supply_shared_controlled_case_executions;
CREATE TRIGGER controlled_case_execution_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_controlled_case_executions
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_immutable();
DROP TRIGGER IF EXISTS controlled_execution_preparation_immutable ON tutor_item_supply_shared_controlled_execution_preparations;
CREATE TRIGGER controlled_execution_preparation_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_controlled_execution_preparations
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_immutable();
DROP TRIGGER IF EXISTS controlled_execution_receipt_immutable ON tutor_item_supply_shared_controlled_execution_receipts;
CREATE TRIGGER controlled_execution_receipt_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_controlled_execution_receipts
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_runtime_immutable();





