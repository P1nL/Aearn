-- ONE closed V3 multiscenario repair group; staged, not installed by registration.
-- Copy of actual 513 control guard, extending only the closed case/slot branch.
-- Deployed 508--514, original receipts and DENY-only ancestry hold remain unchanged.
ALTER TABLE tutor_item_supply_shared_controlled_counterexample_preparations
 DROP CONSTRAINT IF EXISTS item_supply_controlled_experiment_v2_check;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.tutor_item_supply_shared_controlled_counterexample_preparations'::regclass
   AND conname='item_supply_controlled_experiment_v3_check') THEN
   ALTER TABLE tutor_item_supply_shared_controlled_counterexample_preparations
     ADD CONSTRAINT item_supply_controlled_experiment_v3_check CHECK(experiment_key IN
       ('kc-rebinding-wrong-explanation-v1','kc-linked-name-refutation-wrong-rationale-v2',
        'kc-multiscenario-repair-constant-generalization-v3'));
 END IF;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_controlled_counterexample_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE preparation_row tutor_item_supply_shared_controlled_counterexample_preparations%ROWTYPE;
 control_row tutor_item_supply_shared_job_controls%ROWTYPE;
 reservation_row tutor_item_supply_shared_reservations%ROWTYPE;
 settlement_row tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 p jsonb; request_payload jsonb; context_payload jsonb; snapshot jsonb; binding jsonb; envelope jsonb; user_input jsonb; prompt_contract jsonb;
 amount_kind text; amount_value jsonb; same_transaction boolean;
 expected_context_schema text; expected_rule text; expected_seed jsonb; expected_wrong text; expected_program text; expected_blueprint text; expected_slot text:='practice-1';
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='controlled counterexample B1d only'; END IF;
 IF TG_TABLE_NAME='tutor_item_supply_shared_controlled_counterexample_preparations' THEN
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
   SELECT * INTO preparation_row FROM tutor_item_supply_shared_controlled_counterexample_preparations pp WHERE pp.id=NEW.preparation_id FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='controlled original marker required'; END IF;
   SELECT pp.xmin::text::bigint=(txid_current() % 4294967296) INTO same_transaction
     FROM tutor_item_supply_shared_controlled_counterexample_preparations pp WHERE pp.id=NEW.preparation_id;
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

