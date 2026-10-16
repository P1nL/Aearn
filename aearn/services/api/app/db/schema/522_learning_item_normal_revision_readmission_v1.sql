-- Explicit normal_revision_readmission_v1, B1d only. Old509-521 files immutable.
-- Shared-confidential append-only side receipt: not finding discharge/public release.
DO $$ BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='522 B1d only'; END IF;
END $$;
-- Replay must not overwrite an unknown mutation of this new closed authority.
DO $preflight522$
DECLARE expected record; actual record;
BEGIN
 FOR expected IN SELECT * FROM (VALUES
 ('item_supply_internal.assert_normal_revision_readmission(jsonb)','75cd450b6114d5bed0f8be29763e0c2b370189afa1555d5b520d2d1fa0d744cb',ARRAY['p']::text[],'void'),
 ('item_supply_internal.enforce_normal_revision_readmission_insert()','4000dcccef78eb5a6e00039270d96cf26d259e94a9ea51291417d9bd86efe1fd',NULL::text[],'trigger'),
 ('item_supply_internal.normal_revision_readmission_matches(uuid,uuid,text)','5ea5a21ac6fddf078da074274e4fd8efea563afd0ee8c5a4bd5428ecf4deda34',ARRAY['artifact','facts','exact_hash']::text[],'bool')
 ) AS guards(signature,sha256,argnames,returntype) LOOP
  SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
    WHERE p.oid=to_regprocedure(expected.signature);
  IF FOUND AND (encode(sha256(convert_to(replace(actual.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM expected.sha256
    OR actual.lanname<>'plpgsql' OR actual.prokind<>'f' OR actual.proretset OR actual.proisstrict
    OR NOT actual.prosecdef OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
    OR actual.prorettype IS DISTINCT FROM to_regtype('pg_catalog.'||expected.returntype)
    OR actual.pronargs IS DISTINCT FROM COALESCE(cardinality(expected.argnames),0)
    OR actual.proargnames IS DISTINCT FROM expected.argnames
    OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL
    OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
    OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']) THEN
    RAISE check_violation USING MESSAGE='522 unknown normal authority helper body/attributes';
  END IF;
 END LOOP;
END $preflight522$;
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_normal_revision_readmissions (
 id uuid PRIMARY KEY,
 root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
 job_id uuid NOT NULL,
 generation_artifact_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
 lineage_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_revision_lineage(id) ON DELETE RESTRICT,
 recheck_receipt_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_revision_recheck_receipts(id) ON DELETE RESTRICT,
 validation_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
 blind_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
 review_receipt_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
 facts_payload_hash text NOT NULL CHECK(facts_payload_hash ~ '^[0-9a-f]{64}$'),
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=4194304),
 payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 valid_until timestamptz NOT NULL,
 publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
 historical_findings_discharged boolean NOT NULL DEFAULT false CHECK(historical_findings_discharged=false),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);
COMMENT ON TABLE tutor_item_supply_shared_normal_revision_readmissions IS
 'shared-confidential; append-only original normal child/full facts binding; never learner export/purge or historical finding discharge';

CREATE OR REPLACE FUNCTION item_supply_internal.assert_normal_revision_readmission(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE child tutor_item_supply_shared_generation_artifacts%ROWTYPE; parent tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 line tutor_item_supply_shared_revision_lineage%ROWTYPE; rp tutor_item_supply_shared_revision_preparations%ROWTYPE;
 rr tutor_item_supply_shared_revision_recheck_receipts%ROWTYPE; prep tutor_item_supply_shared_revision_recheck_preparations%ROWTYPE;
 vr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; br tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 peer tutor_item_supply_shared_pipeline_receipts%ROWTYPE; vp tutor_item_supply_shared_validation_preparations%ROWTYPE;
 gp tutor_item_supply_shared_generation_policy_bindings%ROWTYPE;
 control_row record; stamp timestamptz; snapshot jsonb; f jsonb:=p->'facts_payload'; roles text[];
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
   OR current_setting('transaction_read_only')<>'off' THEN
   RAISE check_violation USING MESSAGE='normal readmission B1d read committed read-write only';
 END IF;
 SELECT * INTO child FROM tutor_item_supply_shared_generation_artifacts WHERE id=(p->>'artifact_id')::uuid FOR SHARE;
 IF child.id IS NULL OR item_supply_internal.controlled_counterexample_held(child.job_id) IS DISTINCT FROM false THEN
   RAISE check_violation USING MESSAGE='controlled experiment ancestry held';
 END IF;
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','receipt_id','root_id','lineage_id','lineage_hash',
   'recheck_receipt_id','recheck_hash','artifact_id','artifact_hash','lease','binding','validation_preparation_id',
   'validation_receipt_id','validation_hash','blind_receipt_id','blind_hash','review_receipt_id','review_hash',
   'policy_hash','facts_receipt_id','facts_payload_hash','facts_payload','checked_at','valid_until',
   'publication_enabled','historical_findings_discharged']) IS DISTINCT FROM true
   OR p->>'schema_version' IS DISTINCT FROM 'normal_revision_readmission_v1'
   OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
   OR p->'historical_findings_discharged' IS DISTINCT FROM 'false'::jsonb
   OR p->>'receipt_id' IS DISTINCT FROM p->>'facts_receipt_id'
   OR item_supply_internal.native_revision_descendant(child.job_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='closed explicit normal revision permission required';
 END IF;
 SELECT * INTO line FROM tutor_item_supply_shared_revision_lineage WHERE id=(p->>'lineage_id')::uuid FOR SHARE;
 SELECT * INTO rp FROM tutor_item_supply_shared_revision_preparations WHERE id=line.preparation_id FOR SHARE;
 SELECT * INTO parent FROM tutor_item_supply_shared_generation_artifacts WHERE id=line.parent_artifact_id FOR SHARE;
 SELECT * INTO rr FROM tutor_item_supply_shared_revision_recheck_receipts WHERE id=(p->>'recheck_receipt_id')::uuid FOR SHARE;
 SELECT * INTO prep FROM tutor_item_supply_shared_revision_recheck_preparations WHERE id=rr.preparation_id FOR SHARE;
 stamp:=clock_timestamp();
 IF line.id IS NULL OR rp.id IS NULL OR parent.id IS NULL OR rr.id IS NULL OR prep.id IS NULL
   OR line.snapshot_hash IS DISTINCT FROM p->>'lineage_hash' OR rr.snapshot_hash IS DISTINCT FROM p->>'recheck_hash'
   OR (line.root_id,line.child_job_id,line.child_artifact_id) IS DISTINCT FROM (child.root_id,child.job_id,child.id)
   OR (rr.root_id,rr.job_id,rr.generation_artifact_id) IS DISTINCT FROM (child.root_id,child.job_id,child.id)
   OR prep.lineage_id IS DISTINCT FROM line.id OR prep.valid_until<=stamp OR rp.valid_until<=stamp
   OR child.artifact_hash IS DISTINCT FROM p->>'artifact_hash' OR child.root_id::text IS DISTINCT FROM p->>'root_id'
   OR line.payload_json->>'child_substantive_hash' IS DISTINCT FROM item_supply_internal.revision_substantive_hash(child.source_json)
   OR item_supply_internal.revision_substantive_hash(child.source_json)=item_supply_internal.revision_substantive_hash(parent.source_json)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_lineage x WHERE x.id=line.id AND x.xmin::text::bigint=(txid_current()%4294967296))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_recheck_receipts x WHERE x.id=rr.id AND x.xmin::text::bigint=(txid_current()%4294967296))
   OR rr.payload_json->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb
   OR rr.payload_json->'admission_eligible' IS DISTINCT FROM 'false'::jsonb THEN
   RAISE check_violation USING MESSAGE='normal current committed substantive lineage/recheck required';
 END IF;
 SELECT co.*,j.root_id INTO control_row FROM tutor_item_supply_shared_job_controls co
   JOIN tutor_item_supply_shared_jobs j ON j.id=co.job_id WHERE co.job_id=child.job_id FOR SHARE OF co,j;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='normal current child control required'; END IF;
 stamp:=clock_timestamp(); -- Fresh AFTER the control/queue lock wait.
 snapshot:=CASE WHEN control_row.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN control_row.profile_snapshot_json->'profile' ELSE control_row.profile_snapshot_json END;
 IF control_row.state IS DISTINCT FROM 'leased' OR control_row.root_id IS DISTINCT FROM child.root_id
   OR control_row.lease_expires_at IS NULL OR control_row.parent_deadline IS NULL
   OR control_row.lease_expires_at<=stamp OR control_row.parent_deadline<=stamp
   OR p->'lease' IS DISTINCT FROM rr.payload_json->'lease'
   OR p->'lease' IS DISTINCT FROM f->'lease'
   OR p->'lease'->'profile' IS DISTINCT FROM snapshot
   OR p->'lease'->>'job_id' IS DISTINCT FROM child.job_id::text
   OR p->'lease'->>'visibility' IS DISTINCT FROM 'public'
   OR p->'lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
   OR p->'lease'->>'lease_owner' IS DISTINCT FROM control_row.lease_owner
   OR p->'lease'->>'generation' IS DISTINCT FROM control_row.lease_generation::text
   OR p->'lease'->>'state_version' IS DISTINCT FROM control_row.state_version::text
   OR (p->>'checked_at')::timestamptz IS NULL OR (p->>'valid_until')::timestamptz IS NULL
   OR (p->>'checked_at')::timestamptz>stamp OR (p->>'valid_until')::timestamptz<=stamp
   OR (p->>'checked_at')::timestamptz>=(p->>'valid_until')::timestamptz
   OR (p->>'valid_until')::timestamptz>LEAST(rp.valid_until,prep.valid_until,control_row.lease_expires_at,
     control_row.parent_deadline,(snapshot->>'parent_deadline_at')::timestamptz,
     (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')) THEN
   RAISE check_violation USING MESSAGE='normal exact current source/lease bound required';
 END IF;
 SELECT * INTO vr FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(p->>'validation_receipt_id')::uuid FOR SHARE;
 SELECT * INTO br FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(p->>'blind_receipt_id')::uuid FOR SHARE;
 SELECT * INTO peer FROM tutor_item_supply_shared_pipeline_receipts WHERE id=(p->>'review_receipt_id')::uuid FOR SHARE;
 SELECT * INTO vp FROM tutor_item_supply_shared_validation_preparations WHERE id=(p->>'validation_preparation_id')::uuid FOR SHARE;
 SELECT * INTO gp FROM tutor_item_supply_shared_generation_policy_bindings WHERE candidate_id=child.candidate_id FOR SHARE;
 stamp:=clock_timestamp(); -- Fresh AFTER ALL new-stage/policy receipt locks.
 IF vr.id IS NULL OR br.id IS NULL OR peer.id IS NULL OR vp.id IS NULL OR gp.candidate_id IS NULL
   OR (rr.validation_receipt_id,rr.blind_receipt_id,rr.review_receipt_id) IS DISTINCT FROM (vr.id,br.id,peer.id)
   OR (vr.generation_artifact_id,br.generation_artifact_id,peer.generation_artifact_id,vp.generation_artifact_id)
      IS DISTINCT FROM (child.id,child.id,child.id,child.id)
   OR (vr.job_id,br.job_id,peer.job_id,vp.job_id,gp.job_id) IS DISTINCT FROM (child.job_id,child.job_id,child.job_id,child.job_id,child.job_id)
   OR vr.artifact_kind IS DISTINCT FROM 'validation' OR br.artifact_kind IS DISTINCT FROM 'blind_solve'
   OR peer.artifact_kind IS DISTINCT FROM 'review_bundle' OR (vr.mode,br.mode,peer.mode) IS DISTINCT FROM ('live','live','live')
   OR (vr.lease_generation,br.lease_generation,peer.lease_generation,vp.lease_generation,gp.lease_generation)
      IS DISTINCT FROM (control_row.lease_generation,control_row.lease_generation,control_row.lease_generation,control_row.lease_generation,control_row.lease_generation)
   OR (vr.lease_owner,br.lease_owner,peer.lease_owner,vp.lease_owner)
      IS DISTINCT FROM (control_row.lease_owner,control_row.lease_owner,control_row.lease_owner,control_row.lease_owner)
   OR vr.receipt_hash IS DISTINCT FROM p->>'validation_hash' OR br.receipt_hash IS DISTINCT FROM p->>'blind_hash'
   OR peer.receipt_hash IS DISTINCT FROM p->>'review_hash'
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts x WHERE x.id IN (vr.id,br.id,peer.id) AND x.xmin::text::bigint=(txid_current()%4294967296))
   OR p->'binding' IS DISTINCT FROM peer.payload_json->'binding' OR p->'binding' IS DISTINCT FROM br.payload_json->'binding'
   OR peer.payload_json->'blind_solve' IS DISTINCT FROM br.payload_json
   OR peer.payload_json->>'schema_version' IS DISTINCT FROM 'item_supply_review_bundle_v3'
   OR p->>'policy_hash' IS DISTINCT FROM '97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3'
   OR gp.policy_hash IS DISTINCT FROM p->>'policy_hash'
   OR gp.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(child.request_json)
   OR gp.profile_hash IS DISTINCT FROM snapshot->>'profile_hash'
   OR p->'binding'->>'policy_hash' IS DISTINCT FROM gp.policy_hash
   OR p->'binding'->>'source_hash' IS DISTINCT FROM child.source_hash
   OR p->'binding'->>'content_hash' IS DISTINCT FROM child.content_hash
   OR p->'binding'->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'
   OR p->'binding'->>'candidate_key' IS DISTINCT FROM child.item_id::text
   OR p->'binding'->>'version_key' IS DISTINCT FROM child.version_id::text
   OR peer.payload_json->'bundle_version' IS DISTINCT FROM prep.payload_json->'bundle_version'
   OR vr.payload_json->>'schema_version' IS DISTINCT FROM 'candidate_validation_v2'
   OR vr.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
   OR (vr.payload_json->'legacy_receipt' IS DISTINCT FROM 'null'::jsonb AND vr.payload_json->'legacy_receipt'->'passed' IS DISTINCT FROM 'true'::jsonb) THEN
   RAISE check_violation USING MESSAGE='normal original new diagnostic blind/validation/full six binding required';
 END IF;
 SELECT array_agg(role->>'role' ORDER BY role->>'role') INTO roles FROM jsonb_array_elements(peer.payload_json->'reports') role;
 IF roles IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(peer.payload_json->'reports') role
     WHERE role->'binding' IS DISTINCT FROM p->'binding'
       OR role->'run'->>'run_id' IN (SELECT value#>>'{}' FROM jsonb_array_elements(prep.payload_json->'forbidden_run_ids')))
   OR br.payload_json->'run'->>'run_id' IN (SELECT value#>>'{}' FROM jsonb_array_elements(prep.payload_json->'forbidden_run_ids')) THEN
   RAISE check_violation USING MESSAGE='normal independent six/ancestor identities required';
 END IF;
 IF f->>'schema_version' IS DISTINCT FROM 'issued_shared_admission_facts_v1'
   OR p->>'facts_payload_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(f)
   OR f->>'receipt_id' IS DISTINCT FROM p->>'receipt_id' OR f->>'generation_artifact_id' IS DISTINCT FROM child.id::text
   OR f->>'root_id' IS DISTINCT FROM child.root_id::text OR f->>'artifact_hash' IS DISTINCT FROM child.artifact_hash
   OR f->>'item_id' IS DISTINCT FROM child.item_id::text OR f->>'version_id' IS DISTINCT FROM child.version_id::text
   OR f->>'target_id' IS DISTINCT FROM child.target_id OR f->>'target_definition_hash' IS DISTINCT FROM child.target_definition_hash
   OR f->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(vp.payload_json->'spec')
   OR f->'evidence'->'binding' IS DISTINCT FROM p->'binding' OR f->'evaluation'->'binding' IS DISTINCT FROM p->'binding'
   OR f->'evidence'->'source_current' IS DISTINCT FROM 'true'::jsonb
   OR jsonb_typeof(f->'evidence'->'source_claim_receipt_hashes') IS DISTINCT FROM 'array'
   OR jsonb_array_length(f->'evidence'->'source_claim_receipt_hashes')=0
   OR f->'evidence'->'source_claim_receipt_hashes' IS DISTINCT FROM (
      SELECT jsonb_agg(h ORDER BY h) FROM (SELECT DISTINCT leaf.value AS h
        FROM jsonb_array_elements(child.receipt_json->'sources') source
        CROSS JOIN LATERAL jsonb_array_elements(source.value->'claim_receipt_hashes') leaf) hashes)
   OR f->'evaluation'->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(f->'evidence')
   OR f->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR f->'evaluation'->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
   OR f->'evaluation'->>'schema_version' IS DISTINCT FROM 'item_supply_admission_evaluation_v3'
   OR (f->>'checked_at')::timestamptz IS DISTINCT FROM (p->>'checked_at')::timestamptz
   OR (f->>'valid_until')::timestamptz IS DISTINCT FROM (p->>'valid_until')::timestamptz
   OR f->>'validation_preparation_id' IS DISTINCT FROM vp.id::text
   OR f->>'validation_receipt_id' IS DISTINCT FROM vr.id::text OR f->>'validation_receipt_hash' IS DISTINCT FROM vr.receipt_hash
   OR f->>'blind_receipt_id' IS DISTINCT FROM br.id::text OR f->>'blind_receipt_hash' IS DISTINCT FROM br.receipt_hash
   OR f->>'review_receipt_id' IS DISTINCT FROM peer.id::text OR f->>'review_receipt_hash' IS DISTINCT FROM peer.receipt_hash THEN
   RAISE check_violation USING MESSAGE='normal original full facts/evaluation exact hash required';
 END IF;
 -- Last acceptance clock after every lock/current-authority/read/composition.
 -- Earlier snapshots are not proof that a bound survived a lock wait.
 stamp:=clock_timestamp();
 IF item_supply_internal.controlled_counterexample_held(child.job_id) IS DISTINCT FROM false
   OR control_row.lease_expires_at IS NULL OR control_row.parent_deadline IS NULL
   OR stamp>=control_row.lease_expires_at OR stamp>=control_row.parent_deadline
   OR stamp>=rp.valid_until OR stamp>=prep.valid_until
   OR stamp>=(p->>'valid_until')::timestamptz
   OR stamp>=(snapshot->>'parent_deadline_at')::timestamptz
   OR stamp>=(snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
   OR gp.policy_hash IS DISTINCT FROM '97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3'
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(rp.payload_json->'source_deadlines') source_bound
     WHERE (source_bound.value->>'retained_until')::timestamptz IS NULL
       OR (source_bound.value->>'retained_until')::timestamptz<=stamp) THEN
   RAISE check_violation USING MESSAGE='normal readmission final current bound/controlled/policy expired';
 END IF;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_normal_revision_readmission_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 PERFORM item_supply_internal.assert_normal_revision_readmission(NEW.payload_json);
 IF NEW.id::text IS DISTINCT FROM NEW.payload_json->>'receipt_id'
   OR NEW.root_id::text IS DISTINCT FROM NEW.payload_json->>'root_id'
   OR NEW.job_id::text IS DISTINCT FROM NEW.payload_json->'lease'->>'job_id'
   OR NEW.generation_artifact_id::text IS DISTINCT FROM NEW.payload_json->>'artifact_id'
   OR NEW.lineage_id::text IS DISTINCT FROM NEW.payload_json->>'lineage_id'
   OR NEW.recheck_receipt_id::text IS DISTINCT FROM NEW.payload_json->>'recheck_receipt_id'
   OR NEW.validation_receipt_id::text IS DISTINCT FROM NEW.payload_json->>'validation_receipt_id'
   OR NEW.blind_receipt_id::text IS DISTINCT FROM NEW.payload_json->>'blind_receipt_id'
   OR NEW.review_receipt_id::text IS DISTINCT FROM NEW.payload_json->>'review_receipt_id'
   OR NEW.facts_payload_hash IS DISTINCT FROM NEW.payload_json->>'facts_payload_hash'
   OR NEW.valid_until IS DISTINCT FROM (NEW.payload_json->>'valid_until')::timestamptz THEN
   RAISE check_violation USING MESSAGE='normal side receipt exact scalar binding required';
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.normal_revision_readmission_matches(artifact uuid,facts uuid,exact_hash text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r tutor_item_supply_shared_normal_revision_readmissions%ROWTYPE;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_shared_normal_revision_readmissions WHERE id=facts AND generation_artifact_id=artifact FOR SHARE;
 IF NOT FOUND OR exact_hash IS NULL OR r.facts_payload_hash IS DISTINCT FROM exact_hash
   OR r.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(r.payload_json) THEN RETURN false; END IF;
 PERFORM item_supply_internal.assert_normal_revision_readmission(r.payload_json);
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_normal_revision_readmission(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_normal_revision_readmission_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION item_supply_internal.normal_revision_readmission_matches(uuid,uuid,text) FROM PUBLIC;
DROP TRIGGER IF EXISTS normal_revision_readmission_insert ON tutor_item_supply_shared_normal_revision_readmissions;
CREATE TRIGGER normal_revision_readmission_insert BEFORE INSERT ON tutor_item_supply_shared_normal_revision_readmissions
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_normal_revision_readmission_insert();
DROP TRIGGER IF EXISTS normal_revision_readmission_immutable ON tutor_item_supply_shared_normal_revision_readmissions;
CREATE TRIGGER normal_revision_readmission_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_normal_revision_readmissions
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

-- Preserve original509 function signature, owner, ACL, attributes and triggers.
-- One reviewed full-body substitution; unknown/replayed-but-mutated shape fails.
DO $upgrade522$
DECLARE actual record; verified record; source text; definition text; source_hash text;
 baseline_sha256 constant text := 'ba8ee24e3fc7e3eb4ad640ab8de419e547f9b9758e0cd6d7208ad3fe89ef9818';
 revised_sha256 constant text := 'c95c1e10e96c968e4b6377440bcf4fefd23c16271d4640e1940badc8aef10d9b';
 reviewed_body constant text := $body522$
DECLARE artifact_job uuid; normal_fact uuid; exact_hash text;
BEGIN
  SELECT a.job_id INTO artifact_job FROM tutor_item_supply_shared_generation_artifacts a WHERE a.id=NEW.generation_artifact_id;
  -- Controlled ancestry is unconditionally held BEFORE any normal permission.
  IF artifact_job IS NOT NULL AND item_supply_internal.controlled_counterexample_held(artifact_job) IS DISTINCT FROM false THEN
    RAISE check_violation USING MESSAGE='controlled experiment ancestry held';
  END IF;
  IF artifact_job IS NOT NULL AND item_supply_internal.native_revision_descendant(artifact_job) THEN
    IF TG_TABLE_NAME='tutor_item_supply_shared_admission_facts' THEN
      normal_fact:=NEW.id; exact_hash:=item_supply_internal.snapshot_hash(NEW.payload_json);
    ELSIF TG_TABLE_NAME='tutor_learning_item_native_publication_proofs' THEN
      normal_fact:=NEW.facts_receipt_id;
      SELECT f.payload_hash INTO exact_hash FROM tutor_item_supply_shared_admission_facts f
        WHERE f.id=normal_fact AND f.generation_artifact_id=NEW.generation_artifact_id;
    ELSE
      RAISE check_violation USING MESSAGE='normal readmission unknown receiver';
    END IF;
    IF item_supply_internal.normal_revision_readmission_matches(NEW.generation_artifact_id,normal_fact,exact_hash) IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='revision historical blocker discharge owner pending';
    END IF;
  END IF;
  RETURN NEW;
END $body522$;
BEGIN
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
   WHERE p.oid=to_regprocedure('item_supply_internal.deny_revision_admission_without_discharge()');
 IF NOT FOUND OR actual.prokind<>'f' OR actual.lanname<>'plpgsql'
   OR actual.pronargs<>0 OR actual.prorettype<>'pg_catalog.trigger'::regtype OR actual.proretset
   OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u'
   OR actual.provariadic<>0 OR actual.pronargdefaults<>0
   OR actual.proargnames IS NOT NULL OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0 THEN
   RAISE check_violation USING MESSAGE='522 original509 guard attributes mismatch';
 END IF;
 source:=replace(actual.prosrc,E'\r\n',E'\n');
 source_hash:=encode(sha256(convert_to(source,'UTF8')),'hex');
 IF source_hash=revised_sha256 THEN RETURN; END IF;
 IF source_hash IS DISTINCT FROM baseline_sha256
   OR encode(sha256(convert_to(reviewed_body,'UTF8')),'hex') IS DISTINCT FROM revised_sha256 THEN
   RAISE check_violation USING MESSAGE='522 unknown original509 guard body';
 END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1 THEN
   RAISE check_violation USING MESSAGE='522 original509 function framing mismatch';
 END IF;
 EXECUTE replace(definition,actual.prosrc,reviewed_body);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
   OR encode(sha256(convert_to(replace(verified.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM revised_sha256 THEN
   RAISE check_violation USING MESSAGE='522 original509 guard attributes/source not preserved';
 END IF;
END $upgrade522$;


