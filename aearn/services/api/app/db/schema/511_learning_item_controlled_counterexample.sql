-- One default-off B1d controlled KC group. Shared-confidential DATA/DENY only.
-- Append only; never replaces any deployed 440--510 function.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_controlled_counterexample_preparations (
 id uuid PRIMARY KEY, experiment_key text NOT NULL UNIQUE CHECK(experiment_key='kc-rebinding-wrong-explanation-v1'),
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
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_controlled_counterexample_receipts (
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
   REFERENCES tutor_item_supply_shared_controlled_counterexample_preparations(id,root_id,job_id,candidate_id) ON DELETE RESTRICT,
 FOREIGN KEY(reservation_id,job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION item_supply_internal.controlled_counterexample_held(operation_job uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
 WITH RECURSIVE ancestry AS (
   SELECT j.id,j.parent_job_id FROM tutor_item_supply_shared_jobs j WHERE j.id=operation_job
   UNION SELECT j.id,j.parent_job_id FROM tutor_item_supply_shared_jobs j JOIN ancestry aa ON j.id=aa.parent_job_id
 ) SELECT EXISTS(SELECT 1 FROM ancestry aa JOIN tutor_item_supply_shared_controlled_counterexample_preparations pp ON pp.job_id=aa.id)
$$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_controlled_counterexample_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE preparation_row tutor_item_supply_shared_controlled_counterexample_preparations%ROWTYPE;
 control_row tutor_item_supply_shared_job_controls%ROWTYPE;
 reservation_row tutor_item_supply_shared_reservations%ROWTYPE;
 settlement_row tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 p jsonb; request_payload jsonb; context_payload jsonb; snapshot jsonb; binding jsonb; envelope jsonb; user_input jsonb; prompt_contract jsonb;
 amount_kind text; amount_value jsonb; same_transaction boolean;
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
   IF context_payload->>'schema_version' IS DISTINCT FROM 'controlled_kc_counterexample_context_v1'
     OR NOT item_supply_internal.snapshot_keys(context_payload,ARRAY['schema_version','experiment_key','rule_version','target','slot','seed','wrong_explanation','publication_enabled','admission_eligible'])
     OR context_payload->>'experiment_key' IS DISTINCT FROM NEW.experiment_key
     OR context_payload->>'rule_version' IS DISTINCT FROM 'kc_rebinding_wrong_explanation_v1'
     OR context_payload->>'target' IS DISTINCT FROM 'python-kc-binding-v1' OR context_payload->>'slot' IS DISTINCT FROM 'practice-1'
     OR context_payload->'seed' IS DISTINCT FROM '24'::jsonb
     OR context_payload->>'wrong_explanation' IS DISTINCT FROM '执行 price = 8 后，price 会自动恢复成先前的 6，当前 price 仍为 6；变量再次赋值不会改变当前绑定值。'
     OR context_payload->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR context_payload->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
     OR p->>'context_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(context_payload)
     OR p->>'rule_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('rule','kc_rebinding_wrong_explanation_v1',
       'field','/private/content/answer_explanation_markdown','program',E'price = 6\nqty = 3\ntotal = price * qty\nprice = 8\nreceipt = total + 1\nprint(total, receipt)',
       'wrong_explanation',context_payload->>'wrong_explanation'))
     OR request_payload->>'schema_version' IS DISTINCT FROM 'item_generation_request_v2'
     OR request_payload->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
     OR request_payload->'blueprint'->>'version' IS DISTINCT FROM 'finite-public-spec-v3'
     OR request_payload->'blueprint'->>'blueprint_key' IS DISTINCT FROM 'finite.python-kc-binding-v1.practice-1.family-diagnose.s24'
     OR request_payload->'public_template'->>'kind' IS DISTINCT FROM 'knowledge_check'
     OR position(E'price = 6\nqty = 3\ntotal = price * qty\nprice = 8\nreceipt = total + 1\nprint(total, receipt)' in
          COALESCE(request_payload->'public_template'->'content'->>'prompt_markdown',''))=0
     OR request_payload->'demand_binding' IS DISTINCT FROM 'null'::jsonb
     OR request_payload->'profile' IS DISTINCT FROM snapshot OR p->'lease'->'profile' IS DISTINCT FROM snapshot
     OR p->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(request_payload)
     OR p->>'source_bindings_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'sources')
     OR jsonb_typeof(p->'sources') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'sources')<1
     OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'sources') src WHERE src->>'mode' IS DISTINCT FROM 'current_authority')
     OR request_payload->'limits'->'max_output_tokens' IS DISTINCT FROM '61440'::jsonb
     OR request_payload->'limits'->'max_input_bytes' IS DISTINCT FROM '131072'::jsonb
     OR control_row.state IS DISTINCT FROM 'leased' OR control_row.lease_owner IS DISTINCT FROM NEW.lease_owner
     OR control_row.root_id IS DISTINCT FROM NEW.root_id
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

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_controlled_generation_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE preparation_row tutor_item_supply_shared_controlled_counterexample_preparations%ROWTYPE;
 receipt_row tutor_item_supply_shared_controlled_counterexample_receipts%ROWTYPE;
 same_transaction boolean;
BEGIN
 SELECT * INTO preparation_row FROM tutor_item_supply_shared_controlled_counterexample_preparations pp
   WHERE pp.job_id=NEW.job_id OR pp.candidate_id=NEW.candidate_id FOR SHARE;
 IF FOUND THEN
   SELECT * INTO receipt_row FROM tutor_item_supply_shared_controlled_counterexample_receipts rr WHERE rr.preparation_id=preparation_row.id FOR SHARE;
   IF NOT FOUND OR receipt_row.job_id IS DISTINCT FROM NEW.job_id OR receipt_row.root_id IS DISTINCT FROM NEW.root_id
     OR receipt_row.candidate_id IS DISTINCT FROM NEW.candidate_id OR receipt_row.reservation_id IS DISTINCT FROM NEW.reservation_id
     OR receipt_row.payload_json->'result'->>'state' IS DISTINCT FROM 'staged'
     OR receipt_row.payload_json->'result'->'source' IS DISTINCT FROM NEW.source_json
     OR receipt_row.payload_json->'result'->'receipt' IS DISTINCT FROM NEW.receipt_json
     OR preparation_row.payload_json->'request' IS DISTINCT FROM NEW.request_json THEN
     RAISE check_violation USING MESSAGE='controlled parent requires immutable original author trace';
   END IF;
   SELECT rr.xmin::text::bigint=(txid_current() % 4294967296) INTO same_transaction
     FROM tutor_item_supply_shared_controlled_counterexample_receipts rr WHERE rr.id=receipt_row.id;
   IF same_transaction IS DISTINCT FROM false THEN RAISE check_violation USING MESSAGE='controlled committed trace required'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.deny_controlled_counterexample_admission() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE held boolean;
BEGIN
 IF TG_TABLE_NAME='tutor_item_supply_shared_pipeline_receipts' THEN
   IF NEW.artifact_kind<>'admission_evaluation' THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME='tutor_learning_item_publication_events' THEN
   SELECT EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.version_id=NEW.version_id
      AND item_supply_internal.controlled_counterexample_held(aa.job_id)) INTO held;
 ELSE
   SELECT EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.id=NEW.generation_artifact_id
      AND item_supply_internal.controlled_counterexample_held(aa.job_id)) INTO held;
 END IF;
 IF held IS DISTINCT FROM false THEN RAISE check_violation USING MESSAGE='controlled counterexample parent and descendants held'; END IF;
 RETURN NEW;
END $$;

REVOKE ALL ON FUNCTION item_supply_internal.enforce_controlled_counterexample_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_controlled_generation_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.deny_controlled_counterexample_admission() FROM PUBLIC;
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['tutor_item_supply_shared_controlled_counterexample_preparations','tutor_item_supply_shared_controlled_counterexample_receipts'] LOOP
   EXECUTE format('DROP TRIGGER IF EXISTS controlled_insert ON %I',relation_name);
   EXECUTE format('CREATE TRIGGER controlled_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_controlled_counterexample_insert()',relation_name);
   EXECUTE format('DROP TRIGGER IF EXISTS controlled_immutable ON %I',relation_name);
   EXECUTE format('CREATE TRIGGER controlled_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''shared'')',relation_name);
 END LOOP;
 FOREACH relation_name IN ARRAY ARRAY['tutor_item_supply_shared_admission_facts','tutor_item_supply_shared_pipeline_receipts','tutor_learning_item_native_publication_proofs','tutor_learning_item_publication_events'] LOOP
   EXECUTE format('DROP TRIGGER IF EXISTS controlled_no_admission ON %I',relation_name);
   EXECUTE format('CREATE TRIGGER controlled_no_admission BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION item_supply_internal.deny_controlled_counterexample_admission()',relation_name);
 END LOOP;
END $$;
DROP TRIGGER IF EXISTS controlled_generation_insert ON tutor_item_supply_shared_generation_artifacts;
CREATE TRIGGER controlled_generation_insert BEFORE INSERT ON tutor_item_supply_shared_generation_artifacts
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_controlled_generation_insert();
