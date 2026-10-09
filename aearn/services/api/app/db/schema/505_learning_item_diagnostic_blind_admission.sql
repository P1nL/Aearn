-- Explicit completed-diagnostic blind policy, on ORIGINAL canonical roots.
-- Additive only: no historical facts/rows, wallet, source, lease or publication
-- owner is rewritten. Default callers and private481 remain strict V2.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_generation_policy_bindings (
 candidate_id uuid PRIMARY KEY,
 root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
 job_id uuid NOT NULL,
 lease_generation integer NOT NULL CHECK(lease_generation>=1),
 request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
 profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
 policy_hash text NOT NULL CHECK(policy_hash='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3'),
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=16384),
 payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION enforce_item_supply_generation_policy_binding() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE control record; root record; snapshot jsonb; stamp timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed' THEN
   RAISE check_violation USING MESSAGE='diagnostic policy requires B1d read committed';
 END IF;
 SELECT * INTO control FROM tutor_item_supply_shared_job_controls WHERE job_id=NEW.job_id FOR SHARE;
 SELECT b.blueprint_hash INTO root FROM tutor_item_supply_shared_budget_roots r
   JOIN tutor_item_supply_shared_blueprints b ON b.id=r.blueprint_id
   JOIN tutor_item_supply_shared_jobs j ON j.root_id=r.id AND j.id=NEW.job_id
   WHERE r.id=NEW.root_id FOR SHARE OF r,b,j;
 snapshot:=CASE WHEN control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN control.profile_snapshot_json->'profile' ELSE control.profile_snapshot_json END;
 stamp:=clock_timestamp();
 IF control.id IS NULL OR root.blueprint_hash IS NULL OR control.state<>'leased'
   OR control.lease_generation<>NEW.lease_generation OR control.lease_expires_at<=stamp OR control.parent_deadline<=stamp
   OR snapshot->>'profile_hash' IS DISTINCT FROM NEW.profile_hash
   OR NEW.payload_json IS DISTINCT FROM jsonb_build_object(
     'schema_version','shared_generation_policy_binding_v3','policy','{"schema_version":"autonomous_evidence_policy_v3","policy_version":"autonomous_evidence_policy_v3","blind_solve_mode":"completed_diagnostic","publication_enabled":false,"required_review_roles":["curriculum","difficulty","technical","ambiguity","security","adversarial"],"risk_adapter_required":true,"independent_second_bundle_required":true}'::jsonb,
     'root_id',NEW.root_id::text,'job_id',NEW.job_id::text,'candidate_id',NEW.candidate_id::text,
     'request_hash',NEW.request_hash,'blueprint_hash',root.blueprint_hash,'profile_hash',NEW.profile_hash,
     'lease_generation',NEW.lease_generation)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations WHERE job_id=NEW.job_id
       AND reservation_key='gen.'||replace(NEW.candidate_id::text,'-',''))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts WHERE candidate_id=NEW.candidate_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=NEW.job_id) THEN
   RAISE check_violation USING MESSAGE='diagnostic policy must freeze before original author reservation';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_generation_policy_binding() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_generation_policy_binding ON tutor_item_supply_shared_generation_policy_bindings;
CREATE TRIGGER supply_generation_policy_binding BEFORE INSERT ON tutor_item_supply_shared_generation_policy_bindings
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_generation_policy_binding();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_generation_policy_bindings;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_generation_policy_bindings
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

CREATE OR REPLACE FUNCTION item_supply_internal.shared_generation_policy_hash(g tutor_item_supply_shared_generation_artifacts)
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE binding record; blueprint text;
BEGIN
 SELECT * INTO binding FROM tutor_item_supply_shared_generation_policy_bindings WHERE candidate_id=g.candidate_id FOR SHARE;
 IF NOT FOUND THEN RETURN '7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab'; END IF;
 SELECT b.blueprint_hash INTO blueprint FROM tutor_item_supply_shared_budget_roots r
   JOIN tutor_item_supply_shared_blueprints b ON b.id=r.blueprint_id WHERE r.id=g.root_id;
 IF binding.root_id<>g.root_id OR binding.job_id<>g.job_id OR binding.lease_generation<>g.lease_generation
   OR binding.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(g.request_json)
   OR binding.profile_hash IS DISTINCT FROM g.request_json->'profile'->>'profile_hash'
   OR binding.payload_json->>'blueprint_hash' IS DISTINCT FROM blueprint
   OR binding.payload_json->'policy' IS DISTINCT FROM '{"schema_version":"autonomous_evidence_policy_v3","policy_version":"autonomous_evidence_policy_v3","blind_solve_mode":"completed_diagnostic","publication_enabled":false,"required_review_roles":["curriculum","difficulty","technical","ambiguity","security","adversarial"],"risk_adapter_required":true,"independent_second_bundle_required":true}'::jsonb
   OR binding.policy_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(binding.payload_json->'policy') THEN
   RAISE check_violation USING MESSAGE='original generation diagnostic policy mismatch';
 END IF;
 RETURN binding.policy_hash;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.shared_generation_policy_hash(tutor_item_supply_shared_generation_artifacts) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.shared_evaluation_policy_matches(
 g tutor_item_supply_shared_generation_artifacts, evaluation jsonb, review jsonb) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE policy text; expected_warnings jsonb;
BEGIN
 policy:=item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts);
 IF jsonb_typeof(evaluation) IS DISTINCT FROM 'object' OR jsonb_typeof(review) IS DISTINCT FROM 'object'
   OR evaluation->'binding' IS DISTINCT FROM review->'binding'
   OR review->'blind_solve'->'binding' IS DISTINCT FROM review->'binding'
   OR review->'binding'->>'policy_hash' IS DISTINCT FROM policy
   OR review->'blind_solve'->>'state' IS DISTINCT FROM 'completed'
   OR review->'blind_solve'->>'mode' IS DISTINCT FROM 'public_only'
   OR jsonb_typeof(review->'blind_solve'->'score'->'passed') IS DISTINCT FROM 'boolean'
   OR review->>'state' IS DISTINCT FROM 'completed' OR review->>'mode' IS DISTINCT FROM 'peer_blind'
   OR review->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
   OR evaluation->'publication_enabled' IS DISTINCT FROM 'false'::jsonb THEN RETURN false; END IF;
 IF policy='7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab' THEN
   RETURN evaluation->>'schema_version'='item_supply_admission_evaluation_v2'
     AND evaluation->>'policy_version'='autonomous_evidence_policy_v2'
     AND review->>'schema_version'='item_supply_review_bundle_v2'
     AND review->>'policy_version'='autonomous_evidence_policy_v2'
     AND NOT (evaluation ? 'diagnostic_warnings');
 END IF;
 expected_warnings:=CASE WHEN review->'blind_solve'->'score'->'passed'='false'::jsonb
   THEN '["blind_solution_incorrect"]'::jsonb ELSE '[]'::jsonb END;
 RETURN (evaluation->>'schema_version'='item_supply_admission_evaluation_v3'
   AND evaluation->>'policy_version'='autonomous_evidence_policy_v3'
   AND review->>'schema_version'='item_supply_review_bundle_v3'
   AND review->>'policy_version'='autonomous_evidence_policy_v3'
   AND evaluation->'diagnostic_warnings'=expected_warnings) IS TRUE;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.shared_evaluation_policy_matches(tutor_item_supply_shared_generation_artifacts,jsonb,jsonb) FROM PUBLIC;

-- Complete known baseline/revised prosrc pins, including all existing gates.
DO $pin$
DECLARE function_oid oid; source text; definition text;
 baseline_md5 CONSTANT text := '07047f3dd91453ee9942cf951a3fc499'; revised_md5 CONSTANT text := 'e73065634c59badd2d17cb6ef5e95f03';
BEGIN
 function_oid:=to_regprocedure('public.enforce_item_supply_shared_pipeline_artifact()');
 IF function_oid IS NULL THEN RAISE check_violation USING MESSAGE='505 missing baseline public.enforce_item_supply_shared_pipeline_artifact()'; END IF;
 SELECT p.prosrc INTO source FROM pg_proc p WHERE p.oid=function_oid
   AND p.prorettype='pg_catalog.trigger'::regtype AND p.prosecdef
   AND p.prolang=(SELECT oid FROM pg_language WHERE lanname='plpgsql')
   AND p.proconfig=ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'];
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='505 unexpected function attributes'; END IF;
 IF md5(source)=revised_md5 THEN RETURN; END IF;
 IF md5(source) IS DISTINCT FROM baseline_md5 THEN RAISE check_violation USING MESSAGE='505 unknown upstream prosrc'; END IF;
 definition:=pg_get_functiondef(function_oid);
 IF strpos(definition,source)=0 THEN RAISE check_violation USING MESSAGE='505 body framing mismatch'; END IF;
 EXECUTE replace(definition,source,$newbody$
DECLARE control record; facts record; root_facts record; reservation record;
  scope jsonb; snapshot jsonb; material jsonb; source_receipt jsonb; expected_content text; expected_schema text; i integer;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared pipeline outside B1d';
  END IF;
  SELECT * INTO control FROM tutor_item_supply_shared_job_controls WHERE job_id=NEW.job_id FOR UPDATE;
  IF NOT FOUND OR control.state<>'leased' OR control.lease_generation<>NEW.lease_generation
    OR control.state_version<>NEW.lease_state_version OR control.lease_owner IS DISTINCT FROM NEW.lease_owner
    OR control.lease_expires_at IS NULL OR control.lease_expires_at<=clock_timestamp()
    OR control.parent_deadline<=clock_timestamp() THEN
    RAISE check_violation USING MESSAGE='stale shared pipeline lease';
  END IF;
  snapshot:=CASE WHEN control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN control.profile_snapshot_json->'profile' ELSE control.profile_snapshot_json END;
  IF TG_TABLE_NAME='tutor_item_supply_shared_generation_artifacts' THEN
    SELECT b.snapshot_json,o.obligation_json,o.provider_key,r.canonical_key INTO root_facts
      FROM tutor_item_supply_shared_budget_roots r
      JOIN tutor_item_supply_shared_blueprints b ON b.id=r.blueprint_id
      JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id
      WHERE r.id=NEW.root_id AND b.id=NEW.blueprint_id FOR SHARE OF r,b,o;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared pipeline root unavailable'; END IF;
    scope:=root_facts.snapshot_json->'scope';
    SELECT * INTO reservation FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id;
    IF NOT FOUND OR reservation.root_id<>NEW.root_id OR reservation.job_id<>NEW.job_id
      OR reservation.lease_generation<>NEW.lease_generation
      OR reservation.reservation_key IS DISTINCT FROM 'gen.' || replace(NEW.candidate_id::text,'-','')
      OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements
        WHERE reservation_id=NEW.reservation_id AND settlement_key='generation.' || replace(NEW.candidate_id::text,'-','')) THEN
      RAISE check_violation USING MESSAGE='shared pipeline reservation mismatch';
    END IF;
    expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object(
      'item_key',NEW.source_json->'public'->>'item_key','version',NEW.source_json->'public'->>'version',
      'blueprint_hash',item_supply_internal.snapshot_hash(NEW.source_json->'blueprint'),
      'public_hash',item_supply_internal.snapshot_hash(NEW.source_json->'public'),
      'private_hash',item_supply_internal.snapshot_hash(NEW.source_json->'private')));
    IF scope->>'visibility' IS DISTINCT FROM 'public' OR scope->>'owner_ref' IS NOT NULL
      OR NEW.request_json->>'demand_binding' IS NOT NULL
      OR NEW.request_json->'profile' IS DISTINCT FROM snapshot
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(scope)
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM root_facts.obligation_json->>'scope_hash'
      OR item_supply_internal.snapshot_hash(root_facts.obligation_json) IS DISTINCT FROM root_facts.canonical_key
      OR NEW.request_json->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
      OR NEW.receipt_json->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
      OR NEW.receipt_json->>'scope_hash' IS DISTINCT FROM NEW.request_json->>'scope_hash'
      OR NEW.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.source_json)
      OR NEW.content_hash IS DISTINCT FROM expected_content
      OR NEW.receipt_json->>'source_hash' IS DISTINCT FROM NEW.source_hash
      OR NEW.receipt_json->>'content_hash' IS DISTINCT FROM NEW.content_hash
      OR NEW.request_json->'blueprint' IS DISTINCT FROM NEW.source_json->'blueprint'
      OR NEW.source_json->'public'->>'item_key' IS DISTINCT FROM NEW.request_json->>'item_key'
      OR NEW.source_json->'public'->>'version' IS DISTINCT FROM NEW.request_json->>'version'
      OR NEW.item_id IS DISTINCT FROM item_supply_internal.shared_future_item_uuid('item',NEW.request_json->>'item_key')
      OR NEW.version_id IS DISTINCT FROM item_supply_internal.shared_future_item_uuid('version',NEW.request_json->>'item_key' || '@' || (NEW.request_json->>'version'))
      OR item_supply_internal.shared_public_template_matches(NEW.request_json,NEW.source_json->'public',NEW.target_id) IS DISTINCT FROM true
      OR NEW.source_json->'blueprint'->>'knowledge_key' IS DISTINCT FROM scope->>'knowledge_key'
      OR NEW.source_json->'blueprint'->>'language_id' IS DISTINCT FROM scope->>'language_id'
      OR NEW.source_json->'blueprint'->>'item_kind' IS DISTINCT FROM scope->>'item_kind'
      OR NEW.source_json->'blueprint'->>'purpose' IS DISTINCT FROM scope->>'purpose'
      OR NEW.source_json->'blueprint'->'required_capabilities' IS DISTINCT FROM scope->'required_capabilities'
      OR NOT (NEW.source_json->'blueprint'->'allowed_interactions' @> jsonb_build_array(scope->>'interaction'))
      OR scope->>'assessment_contract_version' IS DISTINCT FROM NEW.target_id
      OR scope->>'runtime_profile_id' IS DISTINCT FROM (CASE NEW.target_id
        WHEN 'python-state-update-v1' THEN 'python-stdout-v1' WHEN 'sqlite-predicate-order-v1' THEN 'sqlite-query-v1' ELSE 'static-exact-v1' END)
      OR NEW.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
      OR NEW.receipt_json->'provider'->>'provider' IS DISTINCT FROM root_facts.provider_key
      OR NEW.receipt_json->'provider'->>'model' IS DISTINCT FROM NEW.receipt_json->'provider'->>'configured_model'
      OR NEW.receipt_json->'provider'->>'provider_version' IS DISTINCT FROM 'openai_compatible.v2'
      OR NEW.receipt_json->'provider'->>'prompt_version' IS DISTINCT FROM 'item_author.public_material.v2'
      OR jsonb_typeof(NEW.request_json->'materials') IS DISTINCT FROM 'array'
      OR jsonb_typeof(NEW.receipt_json->'sources') IS DISTINCT FROM 'array' THEN
      RAISE check_violation USING MESSAGE='shared pipeline generation identity mismatch';
    END IF;
    IF jsonb_array_length(NEW.request_json->'materials') NOT BETWEEN 1 AND 12
      OR jsonb_array_length(NEW.receipt_json->'sources')<>jsonb_array_length(NEW.request_json->'materials') THEN
      RAISE check_violation USING MESSAGE='shared pipeline source count mismatch';
    END IF;
    FOR i IN 0..jsonb_array_length(NEW.request_json->'materials')-1 LOOP
      material:=NEW.request_json->'materials'->i;
      source_receipt:=NEW.receipt_json->'sources'->i;
      IF material->'binding'->>'contract_version' IS DISTINCT FROM 'rag_public_course_binding_v1'
        OR material->'binding'->>'target_id' IS DISTINCT FROM NEW.target_id
        OR material->'binding'->>'target_definition_hash' IS DISTINCT FROM NEW.target_definition_hash
        OR material->'binding' ? 'draft' OR material->'binding' ? 'user_id'
        OR material->'access_request'->>'actor_id' IS DISTINCT FROM 'service.rag-public-course'
        OR source_receipt->>'mode' IS DISTINCT FROM 'current_authority'
        OR source_receipt->>'binding_digest' IS DISTINCT FROM material->'binding'->>'binding_digest'
        OR source_receipt->>'corpus_version_id' IS DISTINCT FROM material->'binding'->'evidence'->0->>'corpus_version_id'
        OR source_receipt->>'active_generation' IS DISTINCT FROM material->'binding'->'evidence'->0->>'active_generation'
        OR source_receipt->>'material_digest' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
          'binding',material->'binding','access_request',material->'access_request','exact_claims',material->'exact_claims',
          'excerpt_hash',encode(digest(convert_to(material->>'excerpt','UTF8'),'sha256'),'hex'))) THEN
        RAISE check_violation USING MESSAGE='shared pipeline native source mismatch';
      END IF;
    END LOOP;
  ELSE
    SELECT * INTO facts FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id AND item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,NEW.generation_artifact_id,NEW.continuation_binding_hash);
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared pipeline generation unavailable'; END IF;
    expected_schema:=CASE NEW.artifact_kind WHEN 'validation' THEN 'candidate_validation_v2'
      WHEN 'blind_solve' THEN 'item_supply_blind_receipt_v2' WHEN 'review_bundle' THEN CASE WHEN item_supply_internal.shared_generation_policy_hash(facts::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'item_supply_review_bundle_v3' ELSE 'item_supply_review_bundle_v2' END
      WHEN 'admission_evaluation' THEN CASE WHEN item_supply_internal.shared_generation_policy_hash(facts::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'item_supply_admission_evaluation_v3' ELSE 'item_supply_admission_evaluation_v2' END END;
    IF NEW.schema_version IS DISTINCT FROM expected_schema
      OR COALESCE(NEW.payload_json->>'content_hash',NEW.payload_json->'binding'->>'content_hash') IS DISTINCT FROM facts.content_hash
      OR COALESCE(NEW.payload_json->>'source_hash',NEW.payload_json->'binding'->>'source_hash') IS DISTINCT FROM facts.source_hash
      OR (NEW.artifact_kind<>'validation' AND (
        NEW.payload_json->'binding'->>'candidate_key' IS DISTINCT FROM facts.item_id::text
        OR NEW.payload_json->'binding'->>'version_key' IS DISTINCT FROM facts.version_id::text
        OR NEW.payload_json->'binding'->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'
        OR NEW.payload_json->'binding'->>'policy_hash' IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(facts::tutor_item_supply_shared_generation_artifacts)))
      OR (NEW.payload_json ? 'publication_enabled' AND NEW.payload_json->'publication_enabled'<>'false'::jsonb) THEN
      RAISE check_violation USING MESSAGE='shared pipeline receipt identity mismatch';
    END IF;
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_shared_generation_artifacts' THEN
    PERFORM item_supply_internal.shared_generation_policy_hash(NEW::tutor_item_supply_shared_generation_artifacts);
  END IF;
  RETURN NEW;
END $newbody$);
 IF (SELECT md5(prosrc) FROM pg_proc WHERE oid=function_oid) IS DISTINCT FROM revised_md5 THEN
   RAISE check_violation USING MESSAGE='505 revised prosrc mismatch';
 END IF;
END $pin$;

-- Complete known baseline/revised prosrc pins, including all existing gates.
DO $pin$
DECLARE function_oid oid; source text; definition text;
 baseline_md5 CONSTANT text := 'a7bda9875a794e35ff6885e7ff00bf88'; revised_md5 CONSTANT text := 'cea01aa0446d5bff1d36ec4cd8a3d831';
BEGIN
 function_oid:=to_regprocedure('public.enforce_item_supply_shared_admission_facts()');
 IF function_oid IS NULL THEN RAISE check_violation USING MESSAGE='505 missing baseline public.enforce_item_supply_shared_admission_facts()'; END IF;
 SELECT p.prosrc INTO source FROM pg_proc p WHERE p.oid=function_oid
   AND p.prorettype='pg_catalog.trigger'::regtype AND p.prosecdef
   AND p.prolang=(SELECT oid FROM pg_language WHERE lanname='plpgsql')
   AND p.proconfig=ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'];
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='505 unexpected function attributes'; END IF;
 IF md5(source)=revised_md5 THEN RETURN; END IF;
 IF md5(source) IS DISTINCT FROM baseline_md5 THEN RAISE check_violation USING MESSAGE='505 unknown upstream prosrc'; END IF;
 definition:=pg_get_functiondef(function_oid);
 IF strpos(definition,source)=0 THEN RAISE check_violation USING MESSAGE='505 body framing mismatch'; END IF;
 EXECUTE replace(definition,source,$newbody$
DECLARE p jsonb:=NEW.payload_json; a record; c record; prep record; v record; b record; r record;
  usage record; reservation record; budget jsonb; snapshot jsonb; t timestamptz; kind text; rid uuid;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared facts B1d only';
  END IF;
  SELECT co.*,j.root_id,pr.profile_hash INTO c FROM tutor_item_supply_shared_job_controls co
    JOIN tutor_item_supply_shared_jobs j ON j.id=co.job_id
    JOIN tutor_item_supply_parameter_profiles pr ON pr.id=co.profile_id
    WHERE co.job_id=NEW.job_id FOR SHARE OF co;
  t:=clock_timestamp();
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared facts current job missing'; END IF;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  IF c.state<>'leased' OR c.root_id<>NEW.root_id OR c.profile_hash<>NEW.profile_hash
    OR c.lease_owner IS DISTINCT FROM NEW.lease_owner OR c.lease_generation<>NEW.lease_generation
    OR c.state_version<>NEW.lease_state_version OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR p->'lease'->'profile' IS DISTINCT FROM snapshot
    OR (p->>'checked_at')::timestamptz>t OR (p->>'valid_until')::timestamptz<=t
    OR (p->>'valid_until')::timestamptz>LEAST(c.lease_expires_at,c.parent_deadline,(snapshot->>'parent_deadline_at')::timestamptz)
    OR (p->>'checked_at')::timestamptz>=(p->>'valid_until')::timestamptz THEN
    RAISE check_violation USING MESSAGE='shared facts current lease expired or mismatched';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR a.root_id<>NEW.root_id OR a.item_id<>NEW.item_id OR a.version_id<>NEW.version_id
    OR a.source_hash<>NEW.source_hash OR a.content_hash<>NEW.content_hash
    OR item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,
      NEW.generation_artifact_id,NEW.continuation_binding_hash) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='shared facts original generation/adoption mismatch';
  END IF;
  IF p->>'schema_version' IS DISTINCT FROM 'issued_shared_admission_facts_v1'
    OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->>'receipt_id' IS DISTINCT FROM NEW.id::text OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text
    OR p->>'generation_artifact_id' IS DISTINCT FROM a.id::text OR p->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR p->>'item_id' IS DISTINCT FROM NEW.item_id::text OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
    OR p->>'profile_hash' IS DISTINCT FROM NEW.profile_hash
    OR p->>'continuation_binding_hash' IS DISTINCT FROM NEW.continuation_binding_hash
    OR p->'lease'->>'visibility' IS DISTINCT FROM 'public' OR p->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR p->'lease'->>'lease_owner' IS DISTINCT FROM NEW.lease_owner
    OR p->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
    OR p->'lease'->>'state_version' IS DISTINCT FROM NEW.lease_state_version::text
    OR p->>'target_id' IS DISTINCT FROM a.target_id OR p->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR a.target_id NOT IN ('python-state-update-v1','sqlite-predicate-order-v1','python-kc-binding-v1')
    OR p->'evidence'->'binding'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'evidence'->'binding'->>'content_hash' IS DISTINCT FROM NEW.content_hash
    OR p->'evidence'->'binding'->>'candidate_key' IS DISTINCT FROM NEW.item_id::text
    OR p->'evidence'->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
    OR p->'evidence'->'binding'->>'profile_hash' IS DISTINCT FROM NEW.profile_hash
    OR p->'evaluation'->'binding' IS DISTINCT FROM p->'evidence'->'binding'
    OR p->'evaluation'->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->'evaluation'->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'evidence') THEN
    RAISE check_violation USING MESSAGE='shared facts payload identity mismatch';
  END IF;
  SELECT * INTO prep FROM tutor_item_supply_shared_validation_preparations WHERE id=NEW.validation_preparation_id;
  IF NOT FOUND OR prep.job_id<>NEW.job_id OR prep.lease_generation<>NEW.lease_generation
    OR prep.generation_artifact_id<>a.id OR prep.profile_hash<>NEW.profile_hash
    OR p->>'validation_preparation_id' IS DISTINCT FROM prep.id::text
    OR p->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(prep.payload_json->'spec')
    OR p->>'inputs_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(prep.payload_json->'inputs')
    OR p->>'public_task_hash' IS DISTINCT FROM prep.payload_json->'inputs'->>'public_task_hash'
    OR p->>'instance_hash' IS DISTINCT FROM prep.payload_json->'inputs'->>'instance_hash'
    OR p->>'scorer_version' IS DISTINCT FROM prep.payload_json->'spec'->'coverage_blueprint'->'scope'->>'scorer_version'
    OR p->>'runtime_profile_hash' IS DISTINCT FROM prep.payload_json->'spec'->'coverage_blueprint'->'scope'->>'runtime_profile_hash' THEN
    RAISE check_violation USING MESSAGE='shared facts finite preparation mismatch';
  END IF;
  FOR kind,rid IN SELECT * FROM (VALUES ('validation',NEW.validation_receipt_id),
      ('blind_solve',NEW.blind_receipt_id),('review_bundle',NEW.review_receipt_id)) AS stages(kind,rid) LOOP
    SELECT s.*,s.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO r
      FROM tutor_item_supply_shared_pipeline_receipts s WHERE s.id=rid;
    IF NOT FOUND OR r.same_transaction OR r.job_id<>NEW.job_id OR r.lease_generation<>NEW.lease_generation
      OR r.lease_owner<>NEW.lease_owner OR r.generation_artifact_id<>a.id OR r.mode<>'live'
      OR r.item_id<>NEW.item_id OR r.version_id<>NEW.version_id OR r.source_hash<>NEW.source_hash OR r.content_hash<>NEW.content_hash
      OR r.artifact_kind<>kind OR r.continuation_binding_hash IS DISTINCT FROM NEW.continuation_binding_hash THEN
      RAISE check_violation USING MESSAGE='shared facts separately committed exact stages required';
    END IF;
    IF kind='validation' THEN
      v:=r;
      IF p->>'validation_receipt_id' IS DISTINCT FROM r.id::text OR p->>'validation_receipt_hash' IS DISTINCT FROM r.receipt_hash
        OR p->'evidence'->>'validation_receipt_hash' IS DISTINCT FROM r.receipt_hash THEN
        RAISE check_violation USING MESSAGE='shared facts validation receipt mismatch';
      END IF;
    ELSIF kind='blind_solve' THEN
      b:=r;
      IF p->>'blind_receipt_id' IS DISTINCT FROM r.id::text OR p->>'blind_receipt_hash' IS DISTINCT FROM r.receipt_hash THEN
        RAISE check_violation USING MESSAGE='shared facts blind receipt mismatch';
      END IF;
    ELSE
      IF p->>'review_receipt_id' IS DISTINCT FROM r.id::text OR p->>'review_receipt_hash' IS DISTINCT FROM r.receipt_hash
        OR r.payload_json->'blind_solve' IS DISTINCT FROM b.payload_json THEN
        RAISE check_violation USING MESSAGE='shared facts review receipt mismatch';
      END IF;
    END IF;
  END LOOP;
  FOR kind,budget IN SELECT * FROM (VALUES ('validation',p->'validation_budget'),('review',p->'review_budget')) AS budgets(kind,budget) LOOP
    IF kind='validation' AND a.target_id='python-kc-binding-v1' THEN
      IF budget IS DISTINCT FROM 'null'::jsonb THEN RAISE check_violation USING MESSAGE='static facts have no execution budget'; END IF;
      CONTINUE;
    END IF;
    SELECT * INTO reservation FROM tutor_item_supply_shared_reservations WHERE id=(budget->>'reservation_id')::uuid;
    IF NOT FOUND OR reservation.job_id<>NEW.job_id OR reservation.root_id<>NEW.root_id
      OR reservation.lease_generation<>NEW.lease_generation OR reservation.reservation_key IS DISTINCT FROM budget->>'settlement_key'
      OR reservation.reservation_key<>(CASE WHEN kind='review' THEN 'review.'||replace(a.id::text,'-','') ELSE prep.reservation_key END) THEN
      RAISE check_violation USING MESSAGE='shared facts reservation identity mismatch';
    END IF;
    SELECT s.*,s.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO usage
      FROM tutor_item_supply_shared_runtime_settlements s WHERE s.id=(budget->>'settlement_id')::uuid;
    IF NOT FOUND OR usage.same_transaction OR usage.reservation_id<>reservation.id
      OR usage.settlement_key<>reservation.reservation_key OR usage.usage_state IS DISTINCT FROM budget->>'usage_state'
      OR usage.receipt_hash IS DISTINCT FROM budget->>'receipt_hash'
      OR usage.usage_state<>(CASE WHEN kind='review' THEN 'unknown' ELSE 'known' END) THEN
      RAISE check_violation USING MESSAGE='shared facts separately committed usage required';
    END IF;
    IF kind='review' AND (budget->'actual' IS DISTINCT FROM 'null'::jsonb OR budget->'receipt_hash' IS DISTINCT FROM 'null'::jsonb) THEN
      RAISE check_violation USING MESSAGE='unknown provider usage cannot become zero';
    END IF;
  END LOOP;
  IF p->'ambiguity'->'plan'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'ambiguity'->'plan'->>'specification_hash' IS DISTINCT FROM p->>'specification_hash'
    OR p->'ambiguity'->'plan'->>'inputs_hash' IS DISTINCT FROM p->>'inputs_hash'
    OR (p->'ambiguity'->>'parent_deadline_at')::timestamptz<(p->>'valid_until')::timestamptz THEN
    RAISE check_violation USING MESSAGE='shared facts finite interpretation mismatch';
  END IF;
  IF a.target_id='python-kc-binding-v1' THEN
    IF p->'validation_terminals' IS DISTINCT FROM '[]'::jsonb OR p->'blind_terminals' IS DISTINCT FROM '[]'::jsonb
      OR p->'ambiguity'->>'mode' IS DISTINCT FROM 'static_options'
      OR p->'evidence'->'runner_available' IS DISTINCT FROM 'false'::jsonb
      OR p->'evidence'->'execution_isolated' IS DISTINCT FROM 'false'::jsonb
      OR p->'evidence'->'execution_receipt_hash' IS DISTINCT FROM 'null'::jsonb THEN
      RAISE check_violation USING MESSAGE='static facts cannot claim OS execution';
    END IF;
  ELSIF jsonb_array_length(p->'validation_terminals') NOT BETWEEN 1 AND 32
    OR jsonb_array_length(p->'blind_terminals')<>1 OR p->'ambiguity'->>'mode' IS DISTINCT FROM 'sealed_pair'
    OR p->'evidence'->>'execution_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(v.payload_json->'execution_evidence') THEN
    RAISE check_violation USING MESSAGE='runtime facts original terminal projection missing';
  END IF;
  IF p->'target_proof'<>'null'::jsonb AND (p->'target_proof'->>'claim_scope' IS DISTINCT FROM 'per_item_registered_target_not_inventory'
    OR p->'target_proof'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'target_proof'->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR p->'evidence'->>'coverage_proof_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'target_proof')) THEN
    RAISE check_violation USING MESSAGE='shared facts per-item proof mismatch';
  END IF;
  SELECT * INTO r FROM tutor_item_supply_shared_pipeline_receipts WHERE id=NEW.review_receipt_id;
  IF item_supply_internal.shared_evaluation_policy_matches(a::tutor_item_supply_shared_generation_artifacts,p->'evaluation',r.payload_json) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='shared facts exact frozen policy/warning mismatch';
  END IF;
  RETURN NEW;
END $newbody$);
 IF (SELECT md5(prosrc) FROM pg_proc WHERE oid=function_oid) IS DISTINCT FROM revised_md5 THEN
   RAISE check_violation USING MESSAGE='505 revised prosrc mismatch';
 END IF;
END $pin$;

-- Complete known baseline/revised prosrc pins, including all existing gates.
DO $pin$
DECLARE function_oid oid; source text; definition text;
 baseline_md5 CONSTANT text := '90e7b3f40709765328dc2ce33d80c2a0'; revised_md5 CONSTANT text := '7c572840b467885f9b79573cb108ba74';
BEGIN
 function_oid:=to_regprocedure('public.enforce_learning_item_native_publication_proof()');
 IF function_oid IS NULL THEN RAISE check_violation USING MESSAGE='505 missing baseline public.enforce_learning_item_native_publication_proof()'; END IF;
 SELECT p.prosrc INTO source FROM pg_proc p WHERE p.oid=function_oid
   AND p.prorettype='pg_catalog.trigger'::regtype AND p.prosecdef
   AND p.prolang=(SELECT oid FROM pg_language WHERE lanname='plpgsql')
   AND p.proconfig=ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'];
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='505 unexpected function attributes'; END IF;
 IF md5(source)=revised_md5 THEN RETURN; END IF;
 IF md5(source) IS DISTINCT FROM baseline_md5 THEN RAISE check_violation USING MESSAGE='505 unknown upstream prosrc'; END IF;
 definition:=pg_get_functiondef(function_oid);
 IF strpos(definition,source)=0 THEN RAISE check_violation USING MESSAGE='505 body framing mismatch'; END IF;
 EXECUTE replace(definition,source,$newbody$
DECLARE p jsonb:=NEW.proof_json; f record; e record; g record; v record; c record; snapshot jsonb; t timestamptz;
  clause_data jsonb;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR NEW.publication_txid<>txid_current() THEN
    RAISE check_violation USING MESSAGE='native publication isolated caller transaction required';
  END IF;
  SELECT * INTO f FROM tutor_item_supply_shared_admission_facts WHERE id=NEW.facts_receipt_id FOR SHARE;
  SELECT * INTO e FROM tutor_item_supply_shared_pipeline_receipts WHERE id=NEW.evaluation_receipt_id FOR SHARE;
  SELECT * INTO g FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  SELECT r.*,v1.handle,v1.content_hash AS version_content_hash,v1.risk_tier INTO v
    FROM tutor_learning_item_validation_receipts r JOIN tutor_learning_item_versions v1 ON v1.id=r.version_id
    WHERE r.id=(p->>'bank_validation_id')::uuid AND r.version_id=NEW.version_id;
  IF f.id IS NULL OR e.id IS NULL OR g.id IS NULL OR v.id IS NULL THEN
    RAISE check_violation USING MESSAGE='native publication typed authority missing';
  END IF;
  IF f.version_id<>NEW.version_id OR f.generation_artifact_id<>g.id OR g.version_id<>NEW.version_id
    OR e.generation_artifact_id<>g.id OR e.job_id<>f.job_id OR e.lease_generation<>f.lease_generation
    OR e.artifact_kind<>'admission_evaluation' OR e.schema_version IS DISTINCT FROM (CASE WHEN item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'item_supply_admission_evaluation_v3' ELSE 'item_supply_admission_evaluation_v2' END)
    OR e.payload_json IS DISTINCT FROM f.payload_json->'evaluation'
    OR e.payload_json->>'disposition' IS DISTINCT FROM 'eligible_internal'
    OR e.payload_json->>'policy_version' IS DISTINCT FROM (CASE WHEN item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts)='97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3' THEN 'autonomous_evidence_policy_v3' ELSE 'autonomous_evidence_policy_v2' END)
    OR e.payload_json->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR f.payload_json->'target_proof' IS NULL OR f.payload_json->'target_proof'='null'::jsonb
    OR v.schema_version<>'candidate_validation_v2' OR v.passed IS NOT NULL
    OR v.native_generation_artifact_id<>g.id OR v.native_validation_receipt_id<>f.validation_receipt_id
    OR v.receipt_hash IS DISTINCT FROM f.payload_json->>'validation_receipt_hash'
    OR v.native_specification_hash IS DISTINCT FROM f.payload_json->>'specification_hash'
    OR e.payload_json->'binding'->>'risk_tier' IS DISTINCT FROM v.risk_tier
    OR p->>'proof_id' IS DISTINCT FROM NEW.id::text OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
    OR p->>'item_handle' IS DISTINCT FROM v.handle OR p->>'content_hash' IS DISTINCT FROM v.version_content_hash
    OR p->>'source_hash' IS DISTINCT FROM g.source_hash OR p->>'content_hash' IS DISTINCT FROM g.content_hash
    OR p->>'generation_artifact_id' IS DISTINCT FROM g.id::text
    OR p->>'facts_receipt_id' IS DISTINCT FROM f.id::text OR p->>'facts_hash' IS DISTINCT FROM f.payload_hash
    OR p->>'evaluation_receipt_id' IS DISTINCT FROM e.id::text OR p->>'evaluation_hash' IS DISTINCT FROM e.receipt_hash
    OR p->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(f.payload_json->'evidence')
    OR p->>'evidence_hash' IS DISTINCT FROM e.payload_json->>'evidence_hash'
    OR p->>'validation_receipt_id' IS DISTINCT FROM f.validation_receipt_id::text
    OR p->>'validation_hash' IS DISTINCT FROM f.payload_json->>'validation_receipt_hash'
    OR p->>'review_receipt_id' IS DISTINCT FROM f.review_receipt_id::text
    OR p->>'review_hash' IS DISTINCT FROM f.payload_json->>'review_receipt_hash'
    OR p->'lease' IS DISTINCT FROM f.payload_json->'lease'
    OR p->>'specification_hash' IS DISTINCT FROM f.payload_json->>'specification_hash'
    OR p->>'target_id' IS DISTINCT FROM g.target_id OR p->>'target_definition_hash' IS DISTINCT FROM g.target_definition_hash
    OR p->'materials' IS DISTINCT FROM g.request_json->'materials'
    OR p->'source_receipts' IS DISTINCT FROM g.receipt_json->'sources'
    OR p->'runtime'->>'runtime_profile_hash' IS DISTINCT FROM f.payload_json->>'runtime_profile_hash'
    OR p->'runtime'->>'scorer_version' IS DISTINCT FROM f.payload_json->>'scorer_version'
    OR p->>'policy_hash' IS DISTINCT FROM e.payload_json->'binding'->>'policy_hash'
    OR p->>'materialization_id' IS DISTINCT FROM NEW.materialization_id::text
    OR p->>'publication_event_id' IS DISTINCT FROM NEW.publication_event_id::text
    OR p->>'runner_material_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.runner_material_json)
    OR p->>'origin' IS DISTINCT FROM 'native_internal_b1d'
    OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->'inventory_ready' IS DISTINCT FROM 'false'::jsonb OR p->>'family_independence_status' IS DISTINCT FROM 'pending' THEN
    RAISE check_violation USING MESSAGE='native publication exact V2 provenance mismatch';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('clause_id',m->>'clause_id','clause_hash',m->>'clause_hash',
    'interpretation_hash',m->>'interpretation_hash') ORDER BY n) INTO clause_data
    FROM jsonb_array_elements(f.payload_json->'target_proof'->'mappings') WITH ORDINALITY AS clauses(m,n);
  IF p->'clauses' IS DISTINCT FROM clause_data OR jsonb_array_length(clause_data)<>3 THEN
    RAISE check_violation USING MESSAGE='native publication target clauses missing';
  END IF;
  IF v.risk_tier='high' AND (jsonb_array_length(e.payload_json->'bundle_hashes')<2
      OR jsonb_array_length(f.payload_json->'evidence'->'risk_evidence')=0) THEN
    RAISE check_violation USING MESSAGE='native high risk requires actual V2 adapters and independent bundle';
  END IF;
  IF g.target_id='python-kc-binding-v1' THEN
    IF p->'runtime'->'runtime_lock' IS DISTINCT FROM 'null'::jsonb
      OR p->'runtime'->'runner_version' IS DISTINCT FROM 'null'::jsonb
      OR f.payload_json->'validation_terminals' IS DISTINCT FROM '[]'::jsonb THEN
      RAISE check_violation USING MESSAGE='native static publication cannot claim OS authority';
    END IF;
  ELSIF jsonb_typeof(p->'runtime'->'runtime_lock') IS DISTINCT FROM 'object'
      OR jsonb_array_length(f.payload_json->'validation_terminals')=0 THEN
    RAISE check_violation USING MESSAGE='native runtime publication requires actual sealed evidence';
  END IF;
  SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=f.job_id FOR SHARE;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  t:=clock_timestamp();
  IF c.id IS NULL OR c.state<>'leased' OR c.lease_owner<>f.lease_owner OR c.lease_generation<>f.lease_generation
    OR c.state_version<>f.lease_state_version OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR snapshot IS DISTINCT FROM p->'lease'->'profile' OR (p->>'checked_at')::timestamptz>t
    OR (p->>'valid_until')::timestamptz<=t
    OR (p->>'valid_until')::timestamptz>LEAST(c.lease_expires_at,c.parent_deadline,(f.payload_json->>'valid_until')::timestamptz) THEN
    RAISE check_violation USING MESSAGE='native publication current facts/lease expired';
  END IF;
  IF p->>'policy_hash' IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(g::tutor_item_supply_shared_generation_artifacts) THEN
    RAISE check_violation USING MESSAGE='native publication frozen generation policy mismatch';
  END IF;
  RETURN NEW;
END $newbody$);
 IF (SELECT md5(prosrc) FROM pg_proc WHERE oid=function_oid) IS DISTINCT FROM revised_md5 THEN
   RAISE check_violation USING MESSAGE='505 revised prosrc mismatch';
 END IF;
END $pin$;

-- Complete known baseline/revised prosrc pins, including all existing gates.
DO $pin$
DECLARE function_oid oid; source text; definition text;
 baseline_md5 CONSTANT text := 'c269846bdd5acadf6b1f3b51ffc2b323'; revised_md5 CONSTANT text := '2b3abc768a7198221d805e05bfaddc1e';
BEGIN
 function_oid:=to_regprocedure('item_supply_internal.native_publication_event_allowed(tutor_learning_item_publication_events)');
 IF function_oid IS NULL THEN RAISE check_violation USING MESSAGE='505 missing baseline item_supply_internal.native_publication_event_allowed(tutor_learning_item_publication_events)'; END IF;
 SELECT p.prosrc INTO source FROM pg_proc p WHERE p.oid=function_oid
   AND p.prorettype='pg_catalog.bool'::regtype AND p.prosecdef
   AND p.prolang=(SELECT oid FROM pg_language WHERE lanname='plpgsql')
   AND p.proconfig=ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'];
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='505 unexpected function attributes'; END IF;
 IF md5(source)=revised_md5 THEN RETURN; END IF;
 IF md5(source) IS DISTINCT FROM baseline_md5 THEN RAISE check_violation USING MESSAGE='505 unknown upstream prosrc'; END IF;
 definition:=pg_get_functiondef(function_oid);
 IF strpos(definition,source)=0 THEN RAISE check_violation USING MESSAGE='505 body framing mismatch'; END IF;
 EXECUTE replace(definition,source,$newbody$
DECLARE p record; previous record; expected uuid; required_state text; required_version integer;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR ev.authority_kind<>'native_v2'
    OR ev.policy_version NOT IN ('autonomous_evidence_policy_v2','autonomous_evidence_policy_v3') THEN RETURN false; END IF;
  SELECT q.* INTO p
    FROM tutor_learning_item_native_publication_proofs q WHERE id=ev.authority_reference_id AND version_id=ev.version_id;
  IF NOT FOUND THEN RETURN false; END IF;
  IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts f WHERE f.id=p.facts_receipt_id
    AND f.payload_json->'evaluation'->>'policy_version'=ev.policy_version) THEN RETURN false; END IF;
  IF p.publication_txid<>txid_current() OR ev.authority_hash<>p.proof_hash
    OR ev.content_hash IS DISTINCT FROM p.proof_json->>'content_hash' OR ev.item_handle IS DISTINCT FROM p.proof_json->>'item_handle'
    OR ev.occurred_at<(p.proof_json->>'checked_at')::timestamptz
    OR ev.occurred_at>=(p.proof_json->>'valid_until')::timestamptz OR ev.occurred_at>clock_timestamp()
    OR ev.transition_key IS DISTINCT FROM 'native.'||ev.state||'.'||replace(p.facts_receipt_id::text,'-','')
    OR ev.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
      'proof_hash',p.proof_hash,'state',ev.state,'predecessor',ev.predecessor_event_id::text))
    OR clock_timestamp()>=(p.proof_json->>'valid_until')::timestamptz THEN RETURN false; END IF;
  CASE ev.state
    WHEN 'agent_reviewed' THEN expected:=(p.proof_json->>'review_event_id')::uuid; required_state:='machine_verified'; required_version:=2;
    WHEN 'pilot' THEN expected:=(p.proof_json->>'pilot_event_id')::uuid; required_state:='agent_reviewed'; required_version:=3;
    WHEN 'published' THEN expected:=p.publication_event_id; required_state:='pilot'; required_version:=4;
    ELSE RETURN false;
  END CASE;
  SELECT * INTO previous FROM tutor_learning_item_publication_events WHERE version_id=ev.version_id ORDER BY state_version DESC LIMIT 1;
  IF NOT FOUND OR previous.state<>required_state OR ev.id<>expected OR ev.state_version<>required_version
    OR previous.state_version+1<>ev.state_version OR ev.predecessor_event_id IS DISTINCT FROM previous.id THEN RETURN false; END IF;
  IF ev.state='published' AND NOT EXISTS(SELECT 1 FROM tutor_learning_item_practice_materializations m
    WHERE m.id=p.materialization_id AND m.version_id=ev.version_id AND m.receipt_hash=p.proof_json->>'materialization_hash'
      AND m.native_publication_txid=p.publication_txid) THEN RETURN false; END IF;
  RETURN true;
END $newbody$);
 IF (SELECT md5(prosrc) FROM pg_proc WHERE oid=function_oid) IS DISTINCT FROM revised_md5 THEN
   RAISE check_violation USING MESSAGE='505 revised prosrc mismatch';
 END IF;
END $pin$;
