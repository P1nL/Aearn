--546 explicit fresh committed-child recheck. Historical producer rows/leases are DATA only.
-- Caller owns the atomic transaction; no DDL/provider work is dispatched here.
DO $pre546$ DECLARE actual record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='546 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_committed_child_history(uuid,uuid,uuid)');
 IF false THEN RAISE check_violation USING MESSAGE='546 installed prior receiver required'; END IF;
 IF FOUND AND (encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') NOT IN ('ca07c2265627c477393e318c27cb0667a84fb2efb95682c3aecdec1a57f621c4')
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
   OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype<>to_regtype('pg_catalog.void')
   OR actual.pronargdefaults<>0 OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
 THEN RAISE check_violation USING MESSAGE='546 exact prior/new body and metadata required: item_supply_internal.assert_committed_child_history(uuid,uuid,uuid)'; END IF;
END $pre546$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_committed_child_history(preparation uuid,artifact uuid,lineage_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body546$
DECLARE old_p tutor_item_supply_shared_revision_preparations%ROWTYPE;
 a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 parent_a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 line tutor_item_supply_shared_revision_lineage%ROWTYPE;
 output_row tutor_item_supply_shared_revision_generation_outputs%ROWTYPE;
 settlement tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 adoption tutor_item_supply_shared_candidate_continuations%ROWTYPE;
 phase_row tutor_item_supply_shared_persistent_pack_journal%ROWTYPE;
 parent_version tutor_item_supply_shared_persistent_pack_journal%ROWTYPE;
 control_row tutor_item_supply_shared_job_controls%ROWTYPE;
 operation_row tutor_item_supply_shared_jobs%ROWTYPE;

 profile_data jsonb; stamp timestamptz; bound timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
   OR current_setting('transaction_read_only')<>'off'
   OR preparation IS DISTINCT FROM '4228be3f-a129-4c06-a531-4d69a37c1d46'::uuid
   OR lineage_id IS DISTINCT FROM preparation OR artifact IS DISTINCT FROM '4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3'::uuid
 THEN RAISE check_violation USING MESSAGE='546 exact committed child DATA case required'; END IF;
 SELECT * INTO old_p FROM tutor_item_supply_shared_revision_preparations WHERE id=preparation FOR SHARE;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=artifact FOR SHARE;
 SELECT * INTO line FROM tutor_item_supply_shared_revision_lineage WHERE id=lineage_id FOR SHARE;
 SELECT * INTO parent_a FROM tutor_item_supply_shared_generation_artifacts WHERE id=line.parent_artifact_id FOR SHARE;
 SELECT * INTO output_row FROM tutor_item_supply_shared_revision_generation_outputs WHERE preparation_id=old_p.id FOR SHARE;
 SELECT * INTO settlement FROM tutor_item_supply_shared_runtime_settlements WHERE id=output_row.settlement_id FOR SHARE;
 IF old_p.id IS NULL OR a.id IS NULL OR line.id IS NULL OR parent_a.id IS NULL OR output_row.preparation_id IS NULL
   OR settlement.id IS NULL OR output_row.capture_txid=txid_current()
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations x WHERE x.id=old_p.id AND x.xmin::text::bigint=txid_current()%4294967296)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_lineage x WHERE x.id=line.id AND x.xmin::text::bigint=txid_current()%4294967296)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts x WHERE x.id=a.id AND x.xmin::text::bigint=txid_current()%4294967296)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements x WHERE x.id=settlement.id AND x.xmin::text::bigint=txid_current()%4294967296)
   OR (line.preparation_id,line.child_artifact_id,line.child_job_id,line.root_id,line.parent_artifact_id)
      IS DISTINCT FROM (old_p.id,a.id,a.job_id,a.root_id,old_p.parent_artifact_id)
   OR (old_p.child_job_id,output_row.job_id,output_row.candidate_id,output_row.root_id)
      IS DISTINCT FROM (a.job_id,a.job_id,a.candidate_id,a.root_id)
   OR (line.reservation_id,line.settlement_id,settlement.reservation_id)
      IS DISTINCT FROM (output_row.reservation_id,output_row.settlement_id,output_row.reservation_id)
   OR a.reservation_id IS DISTINCT FROM output_row.reservation_id
   OR output_row.payload_json->>'preparation_hash' IS DISTINCT FROM old_p.snapshot_hash
   OR output_row.payload_json->>'returned_state' IS DISTINCT FROM 'staged'
   OR output_row.payload_json->'result'->>'state' IS DISTINCT FROM 'staged'
   OR output_row.payload_json->'result'->'source' IS DISTINCT FROM a.source_json
   OR output_row.payload_json->'result'->'receipt' IS DISTINCT FROM a.receipt_json
   OR output_row.payload_json->'request' IS DISTINCT FROM a.request_json
   OR output_row.payload_json->'author_input' IS DISTINCT FROM line.payload_json->'author_input'
   OR line.payload_json->>'child_artifact_hash' IS DISTINCT FROM a.artifact_hash
   OR line.payload_json->>'child_substantive_hash' IS DISTINCT FROM item_supply_internal.revision_substantive_hash(a.source_json)
   OR item_supply_internal.revision_substantive_hash(a.source_json)=item_supply_internal.revision_substantive_hash(parent_a.source_json)
   OR settlement.settlement_key IS DISTINCT FROM 'generation.'||replace(a.candidate_id::text,'-','')
   OR settlement.usage_state NOT IN ('known','unknown')
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=a.job_id
      AND cp.lease_generation=a.lease_generation AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=a.artifact_hash)
   OR item_supply_internal.controlled_counterexample_held(a.job_id) IS DISTINCT FROM false
 THEN RAISE check_violation USING MESSAGE='546 original committed durable child/lineage/settlement required'; END IF;
 -- The ORIGINAL source/mapping owner validates the exact stored successor, not the expired producer lease.
 IF item_supply_internal.revision_source_successor_matches(old_p.payload_json) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='546 original source/mapping successor required'; END IF;

END $body546$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_committed_child_history(uuid,uuid,uuid) FROM PUBLIC;
DO $post546$ BEGIN
 IF encode(sha256(convert_to((SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.assert_committed_child_history(uuid,uuid,uuid)')),'UTF8')),'hex') IS DISTINCT FROM 'ca07c2265627c477393e318c27cb0667a84fb2efb95682c3aecdec1a57f621c4'
 THEN RAISE check_violation USING MESSAGE='546 installed exact body mismatch'; END IF;
END $post546$;

DO $pre546$ DECLARE actual record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='546 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.committed_child_version_data_matches(jsonb)');
 IF false THEN RAISE check_violation USING MESSAGE='546 installed prior receiver required'; END IF;
 IF FOUND AND (encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') NOT IN ('ec01b6e9e097aea2b0c7258188ad7083e256807b323b5eafa1356a576c9b08c0')
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
   OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype<>to_regtype('pg_catalog.bool')
   OR actual.pronargdefaults<>0 OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
 THEN RAISE check_violation USING MESSAGE='546 exact prior/new body and metadata required: item_supply_internal.committed_child_version_data_matches(jsonb)'; END IF;
END $pre546$;
CREATE OR REPLACE FUNCTION item_supply_internal.committed_child_version_data_matches(version_data jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body546$
DECLARE p tutor_item_supply_shared_revision_preparations%ROWTYPE;
 a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 line tutor_item_supply_shared_revision_lineage%ROWTYPE;
 phase_row tutor_item_supply_shared_persistent_pack_journal%ROWTYPE;
 operation_row tutor_item_supply_shared_jobs%ROWTYPE;
BEGIN
 IF version_data->>'artifact_id' IS DISTINCT FROM '4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3' THEN RETURN false; END IF;
 PERFORM item_supply_internal.assert_committed_child_history('4228be3f-a129-4c06-a531-4d69a37c1d46',
   '4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3','4228be3f-a129-4c06-a531-4d69a37c1d46');
 SELECT * INTO p FROM tutor_item_supply_shared_revision_preparations WHERE id='4228be3f-a129-4c06-a531-4d69a37c1d46' FOR SHARE;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id='4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3' FOR SHARE;
 SELECT * INTO line FROM tutor_item_supply_shared_revision_lineage WHERE id=p.id FOR SHARE;
 IF version_data->>'revision_id' IS DISTINCT FROM '9bf34de8-7503-544d-bcd6-fde59925826c'
   OR version_data->'specification' IS DISTINCT FROM p.payload_json->'context'->'persistent_family_revision'->'child_specification'
   OR item_supply_internal.snapshot_hash(version_data->'specification') IS DISTINCT FROM p.payload_json->>'specification_hash'
   OR version_data->>'parent_revision_id' IS DISTINCT FROM p.payload_json->'context'->'persistent_family_revision'->>'parent_revision_id'
   OR version_data->>'public_slot_id' IS DISTINCT FROM p.payload_json->'context'->'persistent_family_revision'->>'public_slot_id'
   OR version_data->>'root_id' IS DISTINCT FROM a.root_id::text OR version_data->>'candidate_id' IS DISTINCT FROM a.candidate_id::text
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal parent_v
      WHERE parent_v.record_kind IN('version','qualified') AND parent_v.public_task_id=(version_data->>'public_task_id')::uuid
        AND parent_v.payload_json->>'revision_id'=version_data->>'parent_revision_id'
        AND parent_v.payload_json->>'artifact_id'=line.parent_artifact_id::text
        AND parent_v.payload_json->>'public_slot_id'=version_data->>'public_slot_id'
        AND parent_v.payload_json->>'slot'=version_data->>'slot'
        AND (parent_v.payload_json->>'revision_seq')::integer+1=(version_data->>'revision_seq')::integer)
 THEN RAISE check_violation USING MESSAGE='546 exact same-slot committed child version DATA required'; END IF;
 IF (SELECT count(*) FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.record_kind='phase'
      AND j.public_task_id=(version_data->>'public_task_id')::uuid AND j.payload_json->>'revision_id'=version_data->>'revision_id'
      AND j.operation_key LIKE 'persistent.child.4228be3fa1294c06a5314d69a37c1d46.recheck.frame.%')<>1
 THEN RAISE check_violation USING MESSAGE='546 one fresh committed-child operation required'; END IF;
 SELECT * INTO phase_row FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.record_kind='phase'
   AND j.public_task_id=(version_data->>'public_task_id')::uuid AND j.payload_json->>'revision_id'=version_data->>'revision_id'
   AND j.operation_key='persistent.child.4228be3fa1294c06a5314d69a37c1d46.recheck.frame.1' FOR SHARE;
 IF NOT FOUND OR phase_row.root_id IS DISTINCT FROM a.root_id OR phase_row.payload_json->>'kind' IS DISTINCT FROM 'candidate'
   OR phase_row.payload_json->>'public_slot_id' IS DISTINCT FROM version_data->>'public_slot_id'
 THEN RAISE check_violation USING MESSAGE='546 committed-child version exact finite phase required'; END IF;
 SELECT * INTO operation_row FROM tutor_item_supply_shared_jobs WHERE id=phase_row.job_id FOR SHARE;
 IF operation_row.id IS NULL OR operation_row.parent_job_id IS NOT NULL OR operation_row.id=a.job_id
   OR operation_row.root_id IS DISTINCT FROM a.root_id
   OR item_supply_internal.controlled_counterexample_held(operation_row.id) IS DISTINCT FROM false
 THEN RAISE check_violation USING MESSAGE='546 fresh normal operation required'; END IF;
 PERFORM item_supply_internal.assert_persistent_pack_phase(phase_row.payload_json);
 RETURN true;
END $body546$;
REVOKE ALL ON FUNCTION item_supply_internal.committed_child_version_data_matches(jsonb) FROM PUBLIC;
DO $post546$ BEGIN
 IF encode(sha256(convert_to((SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.committed_child_version_data_matches(jsonb)')),'UTF8')),'hex') IS DISTINCT FROM 'ec01b6e9e097aea2b0c7258188ad7083e256807b323b5eafa1356a576c9b08c0'
 THEN RAISE check_violation USING MESSAGE='546 installed exact body mismatch'; END IF;
END $post546$;

DO $pre546$ DECLARE actual record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='546 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_committed_child_recheck(jsonb,jsonb)');
 IF false THEN RAISE check_violation USING MESSAGE='546 installed prior receiver required'; END IF;
 IF FOUND AND (encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') NOT IN ('35017faca1ef617ff972ffd2777b62d1a1ef9570faf7206865e3c1ab4a5bc7b0')
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
   OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype<>to_regtype('pg_catalog.void')
   OR actual.pronargdefaults<>0 OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
 THEN RAISE check_violation USING MESSAGE='546 exact prior/new body and metadata required: item_supply_internal.assert_committed_child_recheck(jsonb,jsonb)'; END IF;
END $pre546$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_committed_child_recheck(binding jsonb,operation_lease jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body546$
DECLARE old_p tutor_item_supply_shared_revision_preparations%ROWTYPE;
 a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 parent_a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 line tutor_item_supply_shared_revision_lineage%ROWTYPE;
 output_row tutor_item_supply_shared_revision_generation_outputs%ROWTYPE;
 settlement tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 adoption tutor_item_supply_shared_candidate_continuations%ROWTYPE;
 phase_row tutor_item_supply_shared_persistent_pack_journal%ROWTYPE;
 parent_version tutor_item_supply_shared_persistent_pack_journal%ROWTYPE;
 control_row tutor_item_supply_shared_job_controls%ROWTYPE;
 operation_row tutor_item_supply_shared_jobs%ROWTYPE;
 b jsonb:=binding; phase_data jsonb:=binding->'phase'; version_data jsonb:=binding->'version';
 profile_data jsonb; stamp timestamptz; bound timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
   OR current_setting('transaction_read_only')<>'off'
   OR item_supply_internal.snapshot_keys(b,ARRAY['schema_version','preparation_id','preparation_hash','lineage_id',
     'lineage_hash','artifact_id','artifact_hash','producer_job_id','output_hash','settlement_id','adoption_hash',
     'phase','version','source_deadlines','deadline_at']) IS DISTINCT FROM true
   OR b->>'schema_version' IS DISTINCT FROM 'committed_child_recheck_binding_v2'
   OR b->>'preparation_id' IS DISTINCT FROM '4228be3f-a129-4c06-a531-4d69a37c1d46'
   OR b->>'lineage_id' IS DISTINCT FROM b->>'preparation_id'
   OR b->>'artifact_id' IS DISTINCT FROM '4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3'
 THEN RAISE check_violation USING MESSAGE='546 closed exact committed child operation required'; END IF;
 SELECT * INTO old_p FROM tutor_item_supply_shared_revision_preparations WHERE id=(b->>'preparation_id')::uuid FOR SHARE;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=(b->>'artifact_id')::uuid FOR SHARE;
 SELECT * INTO line FROM tutor_item_supply_shared_revision_lineage WHERE id=(b->>'lineage_id')::uuid FOR SHARE;
 SELECT * INTO parent_a FROM tutor_item_supply_shared_generation_artifacts WHERE id=line.parent_artifact_id FOR SHARE;
 SELECT * INTO output_row FROM tutor_item_supply_shared_revision_generation_outputs WHERE preparation_id=old_p.id FOR SHARE;
 SELECT * INTO settlement FROM tutor_item_supply_shared_runtime_settlements WHERE id=output_row.settlement_id FOR SHARE;
 IF old_p.id IS NULL OR a.id IS NULL OR line.id IS NULL OR parent_a.id IS NULL OR output_row.preparation_id IS NULL
   OR settlement.id IS NULL OR output_row.capture_txid=txid_current()
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations x WHERE x.id=old_p.id AND x.xmin::text::bigint=txid_current()%4294967296)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_lineage x WHERE x.id=line.id AND x.xmin::text::bigint=txid_current()%4294967296)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts x WHERE x.id=a.id AND x.xmin::text::bigint=txid_current()%4294967296)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements x WHERE x.id=settlement.id AND x.xmin::text::bigint=txid_current()%4294967296)
   OR (line.preparation_id,line.child_artifact_id,line.child_job_id,line.root_id,line.parent_artifact_id)
      IS DISTINCT FROM (old_p.id,a.id,a.job_id,a.root_id,old_p.parent_artifact_id)
   OR (old_p.child_job_id,output_row.job_id,output_row.candidate_id,output_row.root_id)
      IS DISTINCT FROM (a.job_id,a.job_id,a.candidate_id,a.root_id)
   OR (line.reservation_id,line.settlement_id,settlement.reservation_id)
      IS DISTINCT FROM (output_row.reservation_id,output_row.settlement_id,output_row.reservation_id)
   OR a.reservation_id IS DISTINCT FROM output_row.reservation_id
   OR old_p.snapshot_hash IS DISTINCT FROM b->>'preparation_hash'
   OR line.snapshot_hash IS DISTINCT FROM b->>'lineage_hash' OR a.artifact_hash IS DISTINCT FROM b->>'artifact_hash'
   OR output_row.snapshot_hash IS DISTINCT FROM b->>'output_hash' OR settlement.id::text IS DISTINCT FROM b->>'settlement_id'
   OR a.job_id::text IS DISTINCT FROM b->>'producer_job_id'
   OR output_row.payload_json->>'preparation_hash' IS DISTINCT FROM old_p.snapshot_hash
   OR output_row.payload_json->>'returned_state' IS DISTINCT FROM 'staged'
   OR output_row.payload_json->'result'->>'state' IS DISTINCT FROM 'staged'
   OR output_row.payload_json->'result'->'source' IS DISTINCT FROM a.source_json
   OR output_row.payload_json->'result'->'receipt' IS DISTINCT FROM a.receipt_json
   OR output_row.payload_json->'request' IS DISTINCT FROM a.request_json
   OR output_row.payload_json->'author_input' IS DISTINCT FROM line.payload_json->'author_input'
   OR line.payload_json->>'child_artifact_hash' IS DISTINCT FROM a.artifact_hash
   OR line.payload_json->>'child_substantive_hash' IS DISTINCT FROM item_supply_internal.revision_substantive_hash(a.source_json)
   OR item_supply_internal.revision_substantive_hash(a.source_json)=item_supply_internal.revision_substantive_hash(parent_a.source_json)
   OR settlement.settlement_key IS DISTINCT FROM 'generation.'||replace(a.candidate_id::text,'-','')
   OR settlement.usage_state NOT IN ('known','unknown')
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=a.job_id
      AND cp.lease_generation=a.lease_generation AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=a.artifact_hash)
   OR item_supply_internal.controlled_counterexample_held(a.job_id) IS DISTINCT FROM false
 THEN RAISE check_violation USING MESSAGE='546 original committed durable child/lineage/settlement required'; END IF;
 -- The ORIGINAL source/mapping owner validates the exact stored successor, not the expired producer lease.
 IF item_supply_internal.revision_source_successor_matches(old_p.payload_json) IS DISTINCT FROM true
   OR b->'source_deadlines' IS DISTINCT FROM old_p.payload_json->'source_deadlines'
 THEN RAISE check_violation USING MESSAGE='546 original source/mapping successor required'; END IF;
 SELECT * INTO phase_row FROM tutor_item_supply_shared_persistent_pack_journal WHERE record_kind='phase'
   AND phase_id=(phase_data->>'phase_id')::uuid AND payload_json=phase_data FOR SHARE;
 SELECT * INTO parent_version FROM tutor_item_supply_shared_persistent_pack_journal
   WHERE record_kind IN ('version','qualified') AND public_task_id=phase_row.public_task_id
   AND payload_json->>'revision_id'=version_data->>'parent_revision_id'
   AND payload_json->>'artifact_id'=line.parent_artifact_id::text ORDER BY created_at,id LIMIT 1 FOR SHARE;
 SELECT * INTO adoption FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=(operation_lease->>'job_id')::uuid FOR SHARE;
 SELECT * INTO operation_row FROM tutor_item_supply_shared_jobs WHERE id=adoption.job_id FOR SHARE;
 SELECT * INTO control_row FROM tutor_item_supply_shared_job_controls WHERE job_id=adoption.job_id FOR SHARE;
 profile_data:=CASE WHEN control_row.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN control_row.profile_snapshot_json->'profile' ELSE control_row.profile_snapshot_json END;
 stamp:=clock_timestamp();
 bound:=LEAST((phase_data->>'valid_until')::timestamptz,(old_p.payload_json->'source_deadlines'->0->>'retained_until')::timestamptz);
 IF phase_row.id IS NULL OR parent_version.id IS NULL OR adoption.job_id IS NULL OR operation_row.id IS NULL OR control_row.id IS NULL
   OR (phase_row.root_id,phase_row.job_id,adoption.root_id,adoption.generation_artifact_id,adoption.original_job_id)
      IS DISTINCT FROM (a.root_id,adoption.job_id,a.root_id,a.id,a.job_id)
   OR operation_row.root_id IS DISTINCT FROM a.root_id OR operation_row.parent_job_id IS NOT NULL
   OR phase_data->>'kind' IS DISTINCT FROM 'candidate'
   OR phase_data->>'revision_id' IS DISTINCT FROM version_data->>'revision_id'
   OR phase_data->>'public_slot_id' IS DISTINCT FROM version_data->>'public_slot_id'
   OR version_data->>'public_task_id' IS DISTINCT FROM phase_row.public_task_id::text
   OR version_data->>'public_slot_id' IS DISTINCT FROM parent_version.payload_json->>'public_slot_id'
   OR version_data->>'slot' IS DISTINCT FROM parent_version.payload_json->>'slot'
   OR (version_data->>'revision_seq')::integer IS DISTINCT FROM (parent_version.payload_json->>'revision_seq')::integer+1
   OR version_data->>'candidate_id' IS DISTINCT FROM a.candidate_id::text OR version_data->>'artifact_id' IS DISTINCT FROM a.id::text
   OR version_data->>'root_id' IS DISTINCT FROM a.root_id::text
   OR version_data->'specification' IS DISTINCT FROM old_p.payload_json->'context'->'persistent_family_revision'->'child_specification'
   OR item_supply_internal.snapshot_hash(version_data->'specification') IS DISTINCT FROM old_p.payload_json->>'specification_hash'
   OR version_data->>'parent_revision_id' IS DISTINCT FROM old_p.payload_json->'context'->'persistent_family_revision'->>'parent_revision_id'
   OR version_data->>'public_slot_id' IS DISTINCT FROM old_p.payload_json->'context'->'persistent_family_revision'->>'public_slot_id'
   OR adoption.binding_hash IS DISTINCT FROM b->>'adoption_hash'
   OR adoption.binding_json->'adoption_lease' IS DISTINCT FROM phase_data->'lease'
   OR phase_data->'lease'->'profile' IS DISTINCT FROM profile_data
   OR operation_lease->'profile' IS DISTINCT FROM profile_data
   OR operation_lease->>'job_id' IS DISTINCT FROM adoption.job_id::text
   OR operation_lease->>'lease_owner' IS DISTINCT FROM control_row.lease_owner
   OR operation_lease->>'generation' IS DISTINCT FROM control_row.lease_generation::text
   OR operation_lease->>'state_version' IS DISTINCT FROM control_row.state_version::text
   OR (operation_lease->>'expires_at')::timestamptz IS DISTINCT FROM control_row.lease_expires_at
   OR operation_lease->>'visibility' IS DISTINCT FROM 'public'
   OR operation_lease->'owner_id' IS DISTINCT FROM 'null'::jsonb OR operation_lease->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
   OR control_row.state IS DISTINCT FROM 'leased' OR control_row.lease_expires_at IS NULL OR control_row.parent_deadline IS NULL
   OR stamp>=control_row.lease_expires_at OR stamp>=control_row.parent_deadline
   OR (b->>'deadline_at')::timestamptz IS NULL OR stamp>=(b->>'deadline_at')::timestamptz
   OR (b->>'deadline_at')::timestamptz>bound
   OR item_supply_internal.shared_continuation_generation_inherited(adoption.job_id) IS DISTINCT FROM true
   OR item_supply_internal.controlled_counterexample_held(adoption.job_id) IS DISTINCT FROM false
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts WHERE job_id=adoption.job_id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints WHERE job_id=adoption.job_id AND stage='generating')
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations WHERE job_id=adoption.job_id AND reservation_key LIKE 'gen.%')
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_development_model_accounting_jobs mj
      JOIN tutor_item_supply_development_model_accounting_batches mb ON mb.id=mj.batch_id
      WHERE mj.job_id=adoption.job_id AND mb.root_id=a.root_id AND mb.id=(phase_data->>'batch_id')::uuid
        AND mj.profile_hash=profile_data->>'profile_hash' AND mj.lease_generation=control_row.lease_generation
        AND mb.provider_key='deepseek' AND mb.model='deepseek-flash' AND mb.mode='accounting_only'
        AND mb.valid_until>stamp AND mb.started_at<=stamp)
 THEN RAISE check_violation USING MESSAGE='546 exact fresh phase/slot/491 operation required'; END IF;
 PERFORM item_supply_internal.assert_persistent_pack_phase(phase_data);
 stamp:=clock_timestamp();
 IF stamp>=LEAST((b->>'deadline_at')::timestamptz,control_row.lease_expires_at,control_row.parent_deadline,
    (profile_data->>'parent_deadline_at')::timestamptz,
    (profile_data->>'bound_at')::timestamptz+((profile_data->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond'))
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(b->'source_deadlines') sd
     WHERE COALESCE((sd->>'retained_until')::timestamptz>stamp,false) IS DISTINCT FROM true)
 THEN RAISE check_violation USING MESSAGE='546 final current operation/source bound required'; END IF;
END $body546$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_committed_child_recheck(jsonb,jsonb) FROM PUBLIC;
DO $post546$ BEGIN
 IF encode(sha256(convert_to((SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.assert_committed_child_recheck(jsonb,jsonb)')),'UTF8')),'hex') IS DISTINCT FROM '35017faca1ef617ff972ffd2777b62d1a1ef9570faf7206865e3c1ab4a5bc7b0'
 THEN RAISE check_violation USING MESSAGE='546 installed exact body mismatch'; END IF;
END $post546$;

DO $pre546$ DECLARE actual record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='546 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_normal_revision_readmission_v2(jsonb)');
 IF false THEN RAISE check_violation USING MESSAGE='546 installed prior receiver required'; END IF;
 IF FOUND AND (encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') NOT IN ('de5e9d508af74c23d6e83f3efdfaf0562c799e1625207988840be4fc4b42da5c')
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
   OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype<>to_regtype('pg_catalog.void')
   OR actual.pronargdefaults<>0 OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
 THEN RAISE check_violation USING MESSAGE='546 exact prior/new body and metadata required: item_supply_internal.assert_normal_revision_readmission_v2(jsonb)'; END IF;
END $pre546$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_normal_revision_readmission_v2(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body546$
DECLARE child tutor_item_supply_shared_generation_artifacts%ROWTYPE; parent tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 line tutor_item_supply_shared_revision_lineage%ROWTYPE; rp tutor_item_supply_shared_revision_preparations%ROWTYPE;
 rr tutor_item_supply_shared_revision_recheck_receipts%ROWTYPE; prep tutor_item_supply_shared_revision_recheck_preparations%ROWTYPE;
 vr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; br tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 peer tutor_item_supply_shared_pipeline_receipts%ROWTYPE; vp tutor_item_supply_shared_validation_preparations%ROWTYPE;
 gp tutor_item_supply_shared_generation_policy_bindings%ROWTYPE;
 control_row record; operation_job uuid; stamp timestamptz; snapshot jsonb; f jsonb:=p->'facts_payload'; roles text[];
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
   'publication_enabled','historical_findings_discharged','committed_child']) IS DISTINCT FROM true
   OR p->>'schema_version' IS DISTINCT FROM 'normal_revision_readmission_v2'
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
 operation_job:=(p->'lease'->>'job_id')::uuid;
 PERFORM item_supply_internal.assert_committed_child_recheck(p->'committed_child',p->'lease');
 stamp:=clock_timestamp();
 IF line.id IS NULL OR rp.id IS NULL OR parent.id IS NULL OR rr.id IS NULL OR prep.id IS NULL
   OR line.snapshot_hash IS DISTINCT FROM p->>'lineage_hash' OR rr.snapshot_hash IS DISTINCT FROM p->>'recheck_hash'
   OR (line.root_id,line.child_job_id,line.child_artifact_id) IS DISTINCT FROM (child.root_id,child.job_id,child.id)
   OR (rr.root_id,rr.job_id,rr.generation_artifact_id) IS DISTINCT FROM (child.root_id,operation_job,child.id)
   OR prep.lineage_id IS DISTINCT FROM line.id OR prep.valid_until<=stamp
   OR prep.payload_json->>'schema_version' IS DISTINCT FROM 'native_shared_revision_recheck_preparation_v2'
   OR p->'committed_child' IS DISTINCT FROM prep.payload_json->'committed_child'
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
   JOIN tutor_item_supply_shared_jobs j ON j.id=co.job_id WHERE co.job_id=operation_job FOR SHARE OF co,j;
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
   OR p->'lease'->>'job_id' IS DISTINCT FROM operation_job::text
   OR p->'lease'->>'visibility' IS DISTINCT FROM 'public'
   OR p->'lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb OR p->'lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
   OR p->'lease'->>'lease_owner' IS DISTINCT FROM control_row.lease_owner
   OR p->'lease'->>'generation' IS DISTINCT FROM control_row.lease_generation::text
   OR p->'lease'->>'state_version' IS DISTINCT FROM control_row.state_version::text
   OR (p->>'checked_at')::timestamptz IS NULL OR (p->>'valid_until')::timestamptz IS NULL
   OR (p->>'checked_at')::timestamptz>stamp OR (p->>'valid_until')::timestamptz<=stamp
   OR (p->>'checked_at')::timestamptz>=(p->>'valid_until')::timestamptz
   OR (p->>'valid_until')::timestamptz>LEAST(prep.valid_until,control_row.lease_expires_at,
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
   OR (vr.job_id,br.job_id,peer.job_id,vp.job_id) IS DISTINCT FROM (operation_job,operation_job,operation_job,operation_job)
   OR gp.job_id IS DISTINCT FROM child.job_id OR gp.root_id IS DISTINCT FROM child.root_id
   OR vr.artifact_kind IS DISTINCT FROM 'validation' OR br.artifact_kind IS DISTINCT FROM 'blind_solve'
   OR peer.artifact_kind IS DISTINCT FROM 'review_bundle' OR (vr.mode,br.mode,peer.mode) IS DISTINCT FROM ('live','live','live')
   OR (vr.lease_generation,br.lease_generation,peer.lease_generation,vp.lease_generation)
      IS DISTINCT FROM (control_row.lease_generation,control_row.lease_generation,control_row.lease_generation,control_row.lease_generation)
   OR gp.lease_generation IS DISTINCT FROM child.lease_generation
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
   OR gp.profile_hash IS DISTINCT FROM child.request_json->'profile'->>'profile_hash'
   OR gp.policy_hash IS DISTINCT FROM item_supply_internal.shared_generation_policy_hash(child)
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
   OR stamp>=prep.valid_until
   OR stamp>=(p->>'valid_until')::timestamptz
   OR stamp>=(snapshot->>'parent_deadline_at')::timestamptz
   OR stamp>=(snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
   OR gp.policy_hash IS DISTINCT FROM '97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3'
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(rp.payload_json->'source_deadlines') source_bound
     WHERE (source_bound.value->>'retained_until')::timestamptz IS NULL
       OR (source_bound.value->>'retained_until')::timestamptz<=stamp) THEN
   RAISE check_violation USING MESSAGE='normal readmission final current bound/controlled/policy expired';
 END IF;
END $body546$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_normal_revision_readmission_v2(jsonb) FROM PUBLIC;
DO $post546$ BEGIN
 IF encode(sha256(convert_to((SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.assert_normal_revision_readmission_v2(jsonb)')),'UTF8')),'hex') IS DISTINCT FROM 'de5e9d508af74c23d6e83f3efdfaf0562c799e1625207988840be4fc4b42da5c'
 THEN RAISE check_violation USING MESSAGE='546 installed exact body mismatch'; END IF;
END $post546$;

DO $pre546$ DECLARE actual record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='546 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.enforce_revision_recheck_insert()');
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='546 installed prior receiver required'; END IF;
 IF FOUND AND (encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') NOT IN ('c496c38f8c0a75944c0bb39e4327cd430bd5a1139df71643f625b10a9ac8efe5','9885428fd7199eb110aa5707baf8aa689445bc2233037bbcdb23afff37d5daba')
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
   OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype<>to_regtype('pg_catalog.trigger')
   OR actual.pronargdefaults<>0 OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
 THEN RAISE check_violation USING MESSAGE='546 exact prior/new body and metadata required: item_supply_internal.enforce_revision_recheck_insert()'; END IF;
END $pre546$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_revision_recheck_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body546$
DECLARE prep tutor_item_supply_shared_revision_recheck_preparations%ROWTYPE;
 lineage tutor_item_supply_shared_revision_lineage%ROWTYPE;
 revision_prep tutor_item_supply_shared_revision_preparations%ROWTYPE;
 artifact tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 control_row tutor_item_supply_shared_job_controls%ROWTYPE;
 validation_row tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 blind_row tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 review_row tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 validation_prep tutor_item_supply_shared_validation_preparations%ROWTYPE;
 usage_row tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 reservation_row tutor_item_supply_shared_reservations%ROWTYPE;
 committed boolean:=false;
 p jsonb; receipt jsonb:=NEW.payload_json; lease jsonb; snapshot jsonb; stamp timestamptz;
 old_dispute jsonb; entry jsonb; historical jsonb; provider_run jsonb; property_facts jsonb; expected_property text;
 roles text[]; expected_ancestors jsonb; expected_run_ids jsonb; expected_version integer;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='recheck B1d only'; END IF;
 IF TG_TABLE_NAME='tutor_item_supply_shared_revision_recheck_receipts' THEN
   SELECT * INTO prep FROM tutor_item_supply_shared_revision_recheck_preparations rp WHERE rp.id=NEW.preparation_id FOR SHARE;
   IF NOT FOUND OR (NEW.root_id,NEW.job_id,NEW.generation_artifact_id) IS DISTINCT FROM (prep.root_id,prep.job_id,prep.generation_artifact_id)
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_recheck_preparations rp WHERE rp.id=NEW.preparation_id AND rp.xmin::text::bigint=(txid_current()%4294967296)) THEN
     RAISE check_violation USING MESSAGE='recheck committed original preparation required';
   END IF;
   p:=prep.payload_json; lease:=receipt->'lease';
 ELSE p:=NEW.payload_json; lease:=p->'lease'; END IF;
 committed:=p->>'schema_version'='native_shared_revision_recheck_preparation_v2';
 IF committed THEN
   PERFORM item_supply_internal.assert_committed_child_recheck(p->'committed_child',lease);
   IF p->>'deadline_at' IS DISTINCT FROM p->'committed_child'->>'deadline_at'
     OR (TG_TABLE_NAME='tutor_item_supply_shared_revision_recheck_receipts'
       AND receipt->>'schema_version' IS DISTINCT FROM 'native_shared_revision_recheck_receipt_v2')
   THEN RAISE check_violation USING MESSAGE='546 explicit v2 committed recheck wire required'; END IF;
 ELSE
   IF p->>'schema_version' IS DISTINCT FROM 'native_shared_revision_recheck_preparation_v1'
     OR (TG_TABLE_NAME='tutor_item_supply_shared_revision_recheck_receipts'
       AND receipt->>'schema_version' IS DISTINCT FROM 'native_shared_revision_recheck_receipt_v1')
   THEN RAISE check_violation USING MESSAGE='546 original v1 recheck wire required'; END IF;
 END IF;
 SELECT * INTO lineage FROM tutor_item_supply_shared_revision_lineage ll WHERE ll.id=(p->>'lineage_id')::uuid FOR SHARE;
 SELECT * INTO revision_prep FROM tutor_item_supply_shared_revision_preparations rr WHERE rr.id=lineage.preparation_id FOR SHARE;
 SELECT * INTO artifact FROM tutor_item_supply_shared_generation_artifacts aa WHERE aa.id=NEW.generation_artifact_id FOR SHARE;
 SELECT * INTO control_row FROM tutor_item_supply_shared_job_controls cc WHERE cc.job_id=NEW.job_id FOR UPDATE;
 stamp:=clock_timestamp();
 snapshot:=CASE WHEN control_row.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
   THEN control_row.profile_snapshot_json->'profile' ELSE control_row.profile_snapshot_json END;
 IF (p - ARRAY['schema_version','preparation_id','lineage_id','lineage_hash','root_id','lease','artifact_id','artifact_hash','context_hash','original_disputes','ancestor_reviews','forbidden_run_ids','bundle_version','deadline_at','publication_enabled','blockers_discharged'] - (CASE WHEN committed THEN ARRAY['committed_child'] ELSE ARRAY[]::text[] END)) <> '{}'::jsonb
   OR jsonb_typeof(p->'bundle_version') IS DISTINCT FROM 'number'
   OR jsonb_typeof(lease) IS DISTINCT FROM 'object' THEN
   RAISE check_violation USING MESSAGE='recheck closed typed preparation required';
 END IF;
 IF lineage.id IS NULL OR revision_prep.id IS NULL OR artifact.id IS NULL OR control_row.id IS NULL
   OR lineage.root_id IS DISTINCT FROM NEW.root_id OR lineage.child_artifact_id IS DISTINCT FROM artifact.id
   OR lineage.child_job_id IS DISTINCT FROM artifact.job_id
   OR (NOT committed AND artifact.job_id IS DISTINCT FROM NEW.job_id)
   OR artifact.root_id IS DISTINCT FROM NEW.root_id OR lineage.snapshot_hash IS DISTINCT FROM p->>'lineage_hash'
   OR artifact.artifact_hash IS DISTINCT FROM p->>'artifact_hash' OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text
   OR p->>'artifact_id' IS DISTINCT FROM NEW.generation_artifact_id::text
   OR p->>'context_hash' IS DISTINCT FROM revision_prep.payload_json->>'context_hash'
   OR (NOT committed AND ((p->>'deadline_at')::timestamptz IS DISTINCT FROM revision_prep.valid_until
     OR revision_prep.valid_until<=stamp)) OR control_row.state IS DISTINCT FROM 'leased'
   OR stamp>=LEAST(control_row.parent_deadline,(snapshot->>'parent_deadline_at')::timestamptz,
     (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond'))
   OR control_row.lease_expires_at IS NULL OR control_row.lease_expires_at<=stamp OR control_row.parent_deadline<=stamp
   OR lease->>'job_id' IS DISTINCT FROM NEW.job_id::text OR lease->>'visibility' IS DISTINCT FROM 'public'
   OR lease->'owner_id' IS DISTINCT FROM 'null'::jsonb OR lease->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
   OR lease->>'lease_owner' IS DISTINCT FROM control_row.lease_owner
   OR lease->>'generation' IS DISTINCT FROM control_row.lease_generation::text
   OR lease->>'state_version' IS DISTINCT FROM control_row.state_version::text
   OR lease->'profile' IS DISTINCT FROM snapshot OR p->'lease'->'profile' IS DISTINCT FROM snapshot
   OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR p->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb
   OR p->>'bundle_version' IS NULL OR (p->>'bundle_version')::integer<2
   OR jsonb_typeof(p->'forbidden_run_ids') IS DISTINCT FROM 'array'
   OR jsonb_typeof(p->'original_disputes') IS DISTINCT FROM 'array'
   OR jsonb_array_length(p->'original_disputes') NOT BETWEEN 1 AND 144
   OR jsonb_typeof(p->'ancestor_reviews') IS DISTINCT FROM 'array'
   OR jsonb_array_length(p->'ancestor_reviews') NOT BETWEEN 1 AND 64
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts ff
     WHERE ff.generation_artifact_id=artifact.id OR (NOT committed AND ff.generation_artifact_id=lineage.parent_artifact_id))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr
     WHERE (rr.generation_artifact_id=artifact.id OR (NOT committed AND rr.generation_artifact_id=lineage.parent_artifact_id)) AND rr.artifact_kind='admission_evaluation')
   OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events pe
     JOIN tutor_item_supply_shared_generation_artifacts aa ON aa.version_id=pe.version_id
     WHERE aa.id=artifact.id OR (NOT committed AND aa.id=lineage.parent_artifact_id)) THEN
   RAISE check_violation USING MESSAGE='recheck exact current lineage/source/profile operation required';
 END IF;
 IF p->'original_disputes' IS DISTINCT FROM (SELECT ir.payload_json->'disputes'
   FROM tutor_item_supply_shared_review_investigation_receipts ir
   WHERE ir.id=(revision_prep.payload_json->>'investigation_receipt_id')::uuid) THEN
   RAISE check_violation USING MESSAGE='recheck original issued dispute inventory must remain exact';
 END IF;
 WITH RECURSIVE history AS (
   SELECT ll.parent_artifact_id AS id FROM tutor_item_supply_shared_revision_lineage ll WHERE ll.id=lineage.id
   UNION SELECT ll.parent_artifact_id FROM tutor_item_supply_shared_revision_lineage ll JOIN history hh ON ll.child_artifact_id=hh.id
 ), bundles AS (
   SELECT rr.id,rr.receipt_hash,rr.payload_json FROM tutor_item_supply_shared_pipeline_receipts rr
   JOIN history hh ON hh.id=rr.generation_artifact_id WHERE rr.artifact_kind='review_bundle'
 ), runs AS (
   SELECT bb.payload_json->'blind_solve'->'run'->>'run_id' AS run_id FROM bundles bb
   UNION SELECT pp->'run'->>'run_id' FROM bundles bb CROSS JOIN LATERAL jsonb_array_elements(bb.payload_json->'reports') pp
 ) SELECT (SELECT jsonb_agg(jsonb_build_object('receipt_id',bb.id::text,'receipt_hash',bb.receipt_hash) ORDER BY bb.id) FROM bundles bb),
   (SELECT jsonb_agg(rr.run_id ORDER BY rr.run_id) FROM runs rr),
   (SELECT max((bb.payload_json->>'bundle_version')::integer)+1 FROM bundles bb)
 INTO expected_ancestors,expected_run_ids,expected_version;
 IF expected_ancestors IS NULL OR p->'ancestor_reviews' IS DISTINCT FROM expected_ancestors
   OR p->'forbidden_run_ids' IS DISTINCT FROM expected_run_ids OR (p->>'bundle_version')::integer IS DISTINCT FROM expected_version THEN
   RAISE check_violation USING MESSAGE='recheck complete ancestral identities cannot be dropped';
 END IF;
 -- Original process issuers recheck CURRENT RAG authority at each transaction.
 -- These immutable source hashes/declared retained bounds cannot renew a grant.
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=(CASE WHEN committed THEN artifact.job_id ELSE NEW.job_id END)
   AND (NOT committed OR cp.lease_generation=artifact.lease_generation) AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=artifact.artifact_hash)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(revision_prep.payload_json->'source_deadlines') sd
     WHERE (sd->>'retained_until')::timestamptz<=stamp) THEN
   RAISE check_violation USING MESSAGE='recheck current committed generation/source required';
 END IF;
 FOR historical IN SELECT value FROM jsonb_array_elements(p->'ancestor_reviews') LOOP
   IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=(historical->>'receipt_id')::uuid
     AND rr.artifact_kind='review_bundle' AND rr.receipt_hash=historical->>'receipt_hash'
     AND rr.xmin::text::bigint<>(txid_current()%4294967296)
     AND (rr.payload_json->>'bundle_version')::integer<(p->>'bundle_version')::integer) THEN
     RAISE check_violation USING MESSAGE='recheck committed ancestral review/version missing';
   END IF;
 END LOOP;
 IF TG_TABLE_NAME='tutor_item_supply_shared_revision_recheck_preparations' THEN
   IF NEW.valid_until IS DISTINCT FROM (CASE WHEN committed THEN (p->>'deadline_at')::timestamptz ELSE revision_prep.valid_until END) OR NEW.lineage_id IS DISTINCT FROM lineage.id
     OR p->>'preparation_id' IS DISTINCT FROM NEW.id::text
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=NEW.job_id AND cp.stage='validating' AND cp.status='completed') THEN
     RAISE check_violation USING MESSAGE='recheck preparation must precede full new validation';
   END IF;
 ELSE
   SELECT * INTO validation_row FROM tutor_item_supply_shared_pipeline_receipts vr WHERE vr.id=NEW.validation_receipt_id FOR SHARE;
   SELECT * INTO blind_row FROM tutor_item_supply_shared_pipeline_receipts br WHERE br.id=NEW.blind_receipt_id FOR SHARE;
   SELECT * INTO review_row FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=NEW.review_receipt_id FOR SHARE;
   IF (receipt - ARRAY['schema_version','preparation_id','preparation_hash','lease','artifact_id','lineage_hash','validation_receipt_id','blind_receipt_id','review_receipt_id','review_hash','entries','new_material_disputes','finite_unique_property_hash','publication_enabled','admission_eligible','blockers_discharged']) <> '{}'::jsonb
     OR jsonb_typeof(receipt->'entries') IS DISTINCT FROM 'array'
     OR jsonb_typeof(receipt->'new_material_disputes') IS DISTINCT FROM 'array'
     OR NOT (receipt ? 'finite_unique_property_hash') THEN
     RAISE check_violation USING MESSAGE='recheck closed typed receipt required';
   END IF;
   IF validation_row.id IS NULL OR blind_row.id IS NULL OR review_row.id IS NULL
     OR validation_row.artifact_kind IS DISTINCT FROM 'validation' OR blind_row.artifact_kind IS DISTINCT FROM 'blind_solve'
     OR review_row.artifact_kind IS DISTINCT FROM 'review_bundle'
     OR validation_row.job_id IS DISTINCT FROM NEW.job_id OR blind_row.job_id IS DISTINCT FROM NEW.job_id OR review_row.job_id IS DISTINCT FROM NEW.job_id
     OR validation_row.generation_artifact_id IS DISTINCT FROM artifact.id OR blind_row.generation_artifact_id IS DISTINCT FROM artifact.id
     OR review_row.generation_artifact_id IS DISTINCT FROM artifact.id
     OR validation_row.source_hash IS DISTINCT FROM artifact.source_hash OR review_row.source_hash IS DISTINCT FROM artifact.source_hash
     OR validation_row.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
     OR review_row.payload_json->'blind_solve' IS DISTINCT FROM blind_row.payload_json
     OR review_row.payload_json->>'state' IS DISTINCT FROM 'completed'
     OR review_row.payload_json->>'bundle_version' IS DISTINCT FROM p->>'bundle_version'
     OR review_row.payload_json->'binding'->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id IN (NEW.validation_receipt_id,NEW.blind_receipt_id,NEW.review_receipt_id)
       AND rr.xmin::text::bigint=(txid_current()%4294967296))
     OR receipt->>'preparation_id' IS DISTINCT FROM NEW.preparation_id::text OR receipt->>'preparation_hash' IS DISTINCT FROM prep.snapshot_hash
     OR receipt->>'artifact_id' IS DISTINCT FROM artifact.id::text OR receipt->>'lineage_hash' IS DISTINCT FROM lineage.snapshot_hash
     OR receipt->>'review_hash' IS DISTINCT FROM review_row.receipt_hash
     OR receipt->'new_material_disputes' IS DISTINCT FROM item_supply_internal.revision_recheck_disputes(review_row.payload_json)
     OR validation_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR blind_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR review_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR validation_row.lease_owner IS DISTINCT FROM control_row.lease_owner
     OR blind_row.lease_owner IS DISTINCT FROM control_row.lease_owner
     OR review_row.lease_owner IS DISTINCT FROM control_row.lease_owner
     OR receipt->>'validation_receipt_id' IS DISTINCT FROM NEW.validation_receipt_id::text
     OR receipt->>'blind_receipt_id' IS DISTINCT FROM NEW.blind_receipt_id::text OR receipt->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
     OR receipt->'publication_enabled' IS DISTINCT FROM 'false'::jsonb OR receipt->'admission_eligible' IS DISTINCT FROM 'false'::jsonb
     OR receipt->'blockers_discharged' IS DISTINCT FROM 'false'::jsonb
     OR jsonb_array_length(receipt->'entries') IS DISTINCT FROM jsonb_array_length(p->'original_disputes') THEN
     RAISE check_violation USING MESSAGE='recheck original committed new validation/blind/six receipts required';
   END IF;
   SELECT array_agg(rr->>'role' ORDER BY rr->>'role') INTO roles FROM jsonb_array_elements(review_row.payload_json->'reports') rr;
   IF roles IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[] THEN
     RAISE check_violation USING MESSAGE='recheck all six peer-blind roles required';
   END IF;
   FOR provider_run IN SELECT blind_row.payload_json->'run' UNION ALL
     SELECT rr->'run' FROM jsonb_array_elements(review_row.payload_json->'reports') rr LOOP
     IF provider_run->'max_output_tokens' IS DISTINCT FROM '61440'::jsonb
       OR provider_run->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'
       OR p->'forbidden_run_ids' @> jsonb_build_array(provider_run->>'run_id') THEN
       RAISE check_violation USING MESSAGE='recheck formal output/profile or ancestor run reuse mismatch';
     END IF;
   END LOOP;
   SELECT * INTO reservation_row FROM tutor_item_supply_shared_reservations rs WHERE rs.job_id=NEW.job_id
     AND rs.reservation_key='review.'||replace(artifact.id::text,'-','');
   SELECT * INTO usage_row FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.reservation_id=reservation_row.id
     AND ss.settlement_key=reservation_row.reservation_key;
   IF reservation_row.id IS NULL OR reservation_row.root_id IS DISTINCT FROM NEW.root_id OR reservation_row.requests<>7
     OR reservation_row.lease_generation IS DISTINCT FROM control_row.lease_generation
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
       WHERE ra.reservation_namespace='shared' AND ra.reservation_id=reservation_row.id
         AND ra.resource_kind='output_tokens' AND ra.reserved_amount=430080)
     OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
       WHERE ra.reservation_namespace='shared' AND ra.reservation_id=reservation_row.id
         AND ra.resource_kind='output_tokens' AND ra.reserved_amount<>430080)
     OR usage_row.id IS NULL OR usage_row.usage_state IS DISTINCT FROM 'unknown'
     OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements ss WHERE ss.id=usage_row.id AND ss.xmin::text::bigint=(txid_current()%4294967296)) THEN
     RAISE check_violation USING MESSAGE='recheck committed independent UNKNOWN review allocation required';
   END IF;
   SELECT * INTO validation_prep FROM tutor_item_supply_shared_validation_preparations vv
     WHERE vv.job_id=NEW.job_id AND vv.generation_artifact_id=artifact.id AND vv.lease_generation=control_row.lease_generation;
   property_facts:=validation_prep.payload_json->'inputs'->'static_facts';
   expected_property:=NULL;
   IF property_facts->>'schema_version'='finite_kc_validation_facts_v1'
     AND property_facts->>'source_hash'=artifact.source_hash AND property_facts->'validation'=validation_row.payload_json
     AND (SELECT count(*) FROM jsonb_array_elements(property_facts->'options') oo WHERE oo->'accepted'='true'::jsonb)=1
     AND artifact.source_json->'private'->'content'->'accepted_answers'=jsonb_build_array(property_facts->>'correct_option_id') THEN
     expected_property:=item_supply_internal.snapshot_hash(jsonb_build_object('check','finite_kc_unique_truth_v1',
       'source_hash',artifact.source_hash,'static_facts_hash',item_supply_internal.snapshot_hash(property_facts),
       'scorer_version',property_facts->>'scorer_version','validation_hash',validation_row.receipt_hash));
   END IF;
   IF receipt->'finite_unique_property_hash' IS DISTINCT FROM COALESCE(to_jsonb(expected_property),'null'::jsonb) THEN
     RAISE check_violation USING MESSAGE='recheck exact finite property projection required';
   END IF;
   FOR old_dispute IN SELECT value FROM jsonb_array_elements(p->'original_disputes') LOOP
     IF (SELECT count(*) FROM jsonb_array_elements(receipt->'entries') ee WHERE ee->'original_dispute'=old_dispute)<>1 THEN
       RAISE check_violation USING MESSAGE='recheck every old finding/field identity must remain';
     END IF;
   END LOOP;
   FOR entry IN SELECT value FROM jsonb_array_elements(receipt->'entries') LOOP
     IF jsonb_typeof(entry) IS DISTINCT FROM 'object'
       OR (entry - ARRAY['original_dispute','new_binding','validation_receipt_id','validation_hash','review_receipt_id','review_hash','state','supported_check','issuer_evidence_hash','safe_reason','historical_finding_resolved','publication_enabled']) <> '{}'::jsonb
       OR COALESCE(entry->>'state','') NOT IN ('check_supported','unsupported','unresolved')
       OR entry->>'safe_reason' IS DISTINCT FROM (CASE entry->>'state'
         WHEN 'check_supported' THEN 'finite_property_only_not_claim_resolution'
         WHEN 'unsupported' THEN 'no_clause_specific_adapter' WHEN 'unresolved' THEN 'new_material_dispute_retained' END)
       OR ((entry->>'state'='unresolved') IS DISTINCT FROM EXISTS(
         SELECT 1 FROM jsonb_array_elements(receipt->'new_material_disputes') dd
         WHERE dd->>'safe_code'=entry->'original_dispute'->>'safe_code'))
       OR entry->'new_binding' IS DISTINCT FROM review_row.payload_json->'binding'
       OR entry->>'validation_hash' IS DISTINCT FROM validation_row.receipt_hash OR entry->>'review_hash' IS DISTINCT FROM review_row.receipt_hash
       OR entry->>'validation_receipt_id' IS DISTINCT FROM NEW.validation_receipt_id::text OR entry->>'review_receipt_id' IS DISTINCT FROM NEW.review_receipt_id::text
       OR entry->'historical_finding_resolved' IS DISTINCT FROM 'false'::jsonb OR entry->'publication_enabled' IS DISTINCT FROM 'false'::jsonb THEN
       RAISE check_violation USING MESSAGE='recheck bounded non-authoritative clause data required';
     END IF;
     IF entry->>'state'='check_supported' AND (expected_property IS NULL
       OR entry->>'supported_check' IS DISTINCT FROM 'finite_kc_unique_truth_v1'
       OR entry->>'issuer_evidence_hash' IS DISTINCT FROM expected_property
       OR entry->'original_dispute'->>'safe_code' IS DISTINCT FROM 'unique_answer'
       OR entry->>'safe_reason' IS DISTINCT FROM 'finite_property_only_not_claim_resolution'
       OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(entry->'original_dispute'->'references') rf
         WHERE rf->>'pointer' LIKE '/source/public/content/options%')
       OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(entry->'original_dispute'->'references') rf
         WHERE rf->>'pointer' LIKE '/source/private/content/accepted_answers%')) THEN
       RAISE check_violation USING MESSAGE='recheck concrete finite unique-property issuer required';
     END IF;
     IF entry->>'state'<>'check_supported' AND (entry->'supported_check' IS DISTINCT FROM 'null'::jsonb OR entry->'issuer_evidence_hash' IS DISTINCT FROM 'null'::jsonb) THEN
       RAISE check_violation USING MESSAGE='unsupported historical finding cannot acquire proof';
     END IF;
   END LOOP;
 END IF;
 IF clock_timestamp()>=LEAST((CASE WHEN committed THEN (p->>'deadline_at')::timestamptz ELSE revision_prep.valid_until END),control_row.lease_expires_at,control_row.parent_deadline,
   (snapshot->>'parent_deadline_at')::timestamptz,
   (snapshot->>'bound_at')::timestamptz+((snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')) THEN
   RAISE check_violation USING MESSAGE='recheck final current deadline reached';
 END IF;
 RETURN NEW;
END $body546$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_revision_recheck_insert() FROM PUBLIC;
DO $post546$ BEGIN
 IF encode(sha256(convert_to((SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.enforce_revision_recheck_insert()')),'UTF8')),'hex') IS DISTINCT FROM '9885428fd7199eb110aa5707baf8aa689445bc2233037bbcdb23afff37d5daba'
 THEN RAISE check_violation USING MESSAGE='546 installed exact body mismatch'; END IF;
END $post546$;

DO $pre546$ DECLARE actual record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='546 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_normal_revision_readmission(jsonb)');
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='546 installed prior receiver required'; END IF;
 IF FOUND AND (encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') NOT IN ('75cd450b6114d5bed0f8be29763e0c2b370189afa1555d5b520d2d1fa0d744cb','45d342fc646610142261e290bd12ca7d638a8c5148d37c0e3805d0b90f3bbc6c')
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
   OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype<>to_regtype('pg_catalog.void')
   OR actual.pronargdefaults<>0 OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
 THEN RAISE check_violation USING MESSAGE='546 exact prior/new body and metadata required: item_supply_internal.assert_normal_revision_readmission(jsonb)'; END IF;
END $pre546$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_normal_revision_readmission(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body546$
DECLARE child tutor_item_supply_shared_generation_artifacts%ROWTYPE; parent tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 line tutor_item_supply_shared_revision_lineage%ROWTYPE; rp tutor_item_supply_shared_revision_preparations%ROWTYPE;
 rr tutor_item_supply_shared_revision_recheck_receipts%ROWTYPE; prep tutor_item_supply_shared_revision_recheck_preparations%ROWTYPE;
 vr tutor_item_supply_shared_pipeline_receipts%ROWTYPE; br tutor_item_supply_shared_pipeline_receipts%ROWTYPE;
 peer tutor_item_supply_shared_pipeline_receipts%ROWTYPE; vp tutor_item_supply_shared_validation_preparations%ROWTYPE;
 gp tutor_item_supply_shared_generation_policy_bindings%ROWTYPE;
 control_row record; stamp timestamptz; snapshot jsonb; f jsonb:=p->'facts_payload'; roles text[];
BEGIN
 IF p->>'schema_version'='normal_revision_readmission_v2' THEN
   PERFORM item_supply_internal.assert_normal_revision_readmission_v2(p); RETURN;
 END IF;
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
END $body546$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_normal_revision_readmission(jsonb) FROM PUBLIC;
DO $post546$ BEGIN
 IF encode(sha256(convert_to((SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.assert_normal_revision_readmission(jsonb)')),'UTF8')),'hex') IS DISTINCT FROM '45d342fc646610142261e290bd12ca7d638a8c5148d37c0e3805d0b90f3bbc6c'
 THEN RAISE check_violation USING MESSAGE='546 installed exact body mismatch'; END IF;
END $post546$;

DO $pre546$ DECLARE actual record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='546 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.enforce_persistent_pack_journal_insert()');
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='546 installed prior receiver required'; END IF;
 IF FOUND AND (encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') NOT IN ('59cbbd4d9fcd1eca6f3db40e0733cc9ffdcdd2e77dc14b87bdf6c6d396617de8','5ace67de112f22687c435cbfa432237464832fb735ef04880bb570c5f97003ba')
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
   OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype<>to_regtype('pg_catalog.trigger')
   OR actual.pronargdefaults<>0 OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
 THEN RAISE check_violation USING MESSAGE='546 exact prior/new body and metadata required: item_supply_internal.enforce_persistent_pack_journal_insert()'; END IF;
END $pre546$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_persistent_pack_journal_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body546$
DECLARE p jsonb:=NEW.payload_json; parent record; proof record; phase record; header record; artifact record;
 private_header record;private_job record;private_control record;private_ref jsonb;private_lease jsonb;private_profile jsonb;fixed_slot jsonb;stamp timestamptz;
 committed_child_data boolean:=false;
 slots text[]:=ARRAY['practice-1','practice-2','assessment-1','assessment-2','guided-remediation']; slot_index integer;
BEGIN
 IF TG_TABLE_NAME='tutor_item_supply_private_persistent_pack_journal' THEN
  PERFORM user_id FROM tutor_item_supply_user_epochs WHERE user_id=NEW.user_id AND epoch=NEW.epoch AND enabled FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 private epoch stale'; END IF;
  PERFORM id FROM tutor_item_supply_private_scopes WHERE id=NEW.scope_id AND user_id=NEW.user_id AND epoch=NEW.epoch FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 private scope stale'; END IF;
  IF NEW.record_kind='task' THEN
   IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','ref','slots','enhancement']) IS DISTINCT FROM true
    OR item_supply_internal.snapshot_keys(p->'ref',ARRAY['schema_version','pack_task_id','user_id','epoch','scope_id','mapping_receipt_id','demand_id','intent_hash','public_task_id']) IS DISTINCT FROM true
    OR p->>'schema_version' IS DISTINCT FROM 'persistent_pack_task_record_v1'
    OR p->'ref'->>'schema_version' IS DISTINCT FROM 'persistent_pack_task_ref_v1'
    OR NEW.id IS DISTINCT FROM NEW.pack_task_id OR (p->'ref'->>'pack_task_id')::uuid IS DISTINCT FROM NEW.id
    OR (p->'ref'->>'user_id')::uuid IS DISTINCT FROM NEW.user_id OR (p->'ref'->>'epoch')::integer IS DISTINCT FROM NEW.epoch
    OR (p->'ref'->>'scope_id')::uuid IS DISTINCT FROM NEW.scope_id OR p->'ref'->>'intent_hash' IS DISTINCT FROM NEW.intent_hash
    OR COALESCE(p->>'enhancement' IN('base_only','prefer_private'),false) IS DISTINCT FROM true
    OR jsonb_typeof(p->'slots') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'slots') IS DISTINCT FROM 5
   THEN RAISE check_violation USING MESSAGE='523 exact ONE private task five stable slots required'; END IF;
   SELECT * INTO header FROM tutor_item_supply_shared_persistent_pack_journal
    WHERE public_task_id=(p->'ref'->>'public_task_id')::uuid AND record_kind='task' FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 private task public attachment missing'; END IF;
   FOR slot_index IN 0..4 LOOP
    IF item_supply_internal.snapshot_keys(p->'slots'->slot_index,ARRAY['schema_version','slot_id','logical_item_id','slot','public_slot_id']) IS DISTINCT FROM true
     OR p->'slots'->slot_index->>'schema_version' IS DISTINCT FROM 'persistent_pack_slot_ref_v1'
     OR p->'slots'->slot_index->>'slot' IS DISTINCT FROM slots[slot_index+1]
     OR p->'slots'->slot_index->'public_slot_id' IS DISTINCT FROM header.payload_json->'public_slots'->slot_index
     OR COALESCE(p->'slots'->slot_index->>'slot_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
     OR COALESCE(p->'slots'->slot_index->>'logical_item_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='523 exact private slot attachment required'; END IF;
   END LOOP;
   IF (SELECT count(DISTINCT s->>'slot_id') FROM jsonb_array_elements(p->'slots') s)<>5
    OR (SELECT count(DISTINCT s->>'logical_item_id') FROM jsonb_array_elements(p->'slots') s)<>5
   THEN RAISE check_violation USING MESSAGE='523 private slots must be unique'; END IF;
   PERFORM id FROM tutor_item_supply_finite_course_mappings m WHERE m.id=(p->'ref'->>'mapping_receipt_id')::uuid
    AND m.user_id=NEW.user_id AND m.epoch=NEW.epoch AND m.assessment_scope_id=NEW.scope_id
    AND (p->'ref'->>'demand_id')::uuid IN(m.practice_demand_id,m.assessment_demand_id,m.remediation_demand_id) FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 original confirmed mapping demand required'; END IF;
  ELSE
   PERFORM id FROM tutor_item_supply_private_persistent_pack_journal WHERE id=NEW.pack_task_id
    AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND intent_hash=NEW.intent_hash AND record_kind='task' FOR SHARE;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 private original task required'; END IF;
   IF NEW.record_kind='phase' THEN
    IF p->>'schema_version'='persistent_private_phase_attachment_v1' THEN
     IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','phase_id','public_task_id']) IS DISTINCT FROM true
     THEN RAISE check_violation USING MESSAGE='523 private PUBLIC attachment schema required'; END IF;
     PERFORM id FROM tutor_item_supply_shared_persistent_pack_journal WHERE record_kind='phase'
      AND phase_id=(p->>'phase_id')::uuid AND public_task_id=(p->>'public_task_id')::uuid FOR SHARE;
     IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 private original PUBLIC phase required'; END IF;
    ELSIF p->>'schema_version'='private_native_phase_v1' THEN
     -- Exact A524 native PRIVATE phase DATA. Never a SHARED lease/attachment.
     IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','root_id','job_id','slot_id','business_item_id','goal_scope_id','ref','lease','valid_until']) IS DISTINCT FROM true
      OR item_supply_internal.snapshot_keys(p->'ref',ARRAY['pack_task_id','slot_id','business_item_id','root_id','mapping_receipt_id','user_id','epoch','scope_id','goal_scope_id','slot','parent_version_id']) IS DISTINCT FROM true
      OR item_supply_internal.snapshot_keys(p->'lease',ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
     THEN RAISE check_violation USING MESSAGE='523 exact native PRIVATE phase schema required'; END IF;
     private_ref:=p->'ref';private_lease:=p->'lease';
     SELECT * INTO private_header FROM tutor_item_supply_private_persistent_pack_journal WHERE id=NEW.pack_task_id
      AND pack_task_id=id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND record_kind='task' FOR SHARE;
     IF NOT FOUND OR (private_ref->>'pack_task_id')::uuid IS DISTINCT FROM NEW.pack_task_id
      OR (private_ref->>'user_id')::uuid IS DISTINCT FROM NEW.user_id OR (private_ref->>'epoch')::bigint IS DISTINCT FROM NEW.epoch
      OR (private_ref->>'scope_id')::uuid IS DISTINCT FROM NEW.scope_id
      OR private_ref->>'mapping_receipt_id' IS DISTINCT FROM private_header.payload_json->'ref'->>'mapping_receipt_id'
      OR private_lease->>'visibility' IS DISTINCT FROM 'private' OR private_lease->>'owner_id' IS DISTINCT FROM private_ref->>'user_id'
      OR private_lease->'owner_epoch' IS DISTINCT FROM private_ref->'epoch' OR jsonb_typeof(private_ref->'epoch') IS DISTINCT FROM 'number'
      OR private_lease->>'job_id' IS DISTINCT FROM p->>'job_id' OR private_ref->>'root_id' IS DISTINCT FROM p->>'root_id'
      OR private_ref->>'slot_id' IS DISTINCT FROM p->>'slot_id' OR private_ref->>'business_item_id' IS DISTINCT FROM p->>'business_item_id'
      OR private_ref->>'goal_scope_id' IS DISTINCT FROM p->>'goal_scope_id'
      OR NEW.operation_key IS DISTINCT FROM ('private.phase.'||(p->>'job_id'))
      OR (private_ref->'parent_version_id' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(private_ref->'parent_version_id') IS DISTINCT FROM 'string'
       OR COALESCE(private_ref->>'parent_version_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true))
     THEN RAISE check_violation USING MESSAGE='523 exact native PRIVATE task owner/phase required'; END IF;
     SELECT s INTO fixed_slot FROM jsonb_array_elements(private_header.payload_json->'slots') s
      WHERE s->>'slot_id'=private_ref->>'slot_id' AND s->>'logical_item_id'=private_ref->>'business_item_id';
     IF fixed_slot IS NULL OR private_ref->>'slot' IS DISTINCT FROM
      (CASE WHEN fixed_slot->>'slot' IN('practice-1','practice-2') THEN 'practice'
       WHEN fixed_slot->>'slot' IN('assessment-1','assessment-2') THEN 'assessment' ELSE 'remediation' END)
     THEN RAISE check_violation USING MESSAGE='523 native PRIVATE fixed business slot/role required'; END IF;
     SELECT j.* INTO private_job FROM tutor_item_supply_private_jobs j WHERE j.id=(p->>'job_id')::uuid
      AND j.root_id=(p->>'root_id')::uuid AND j.user_id=NEW.user_id AND j.epoch=NEW.epoch AND j.scope_id=NEW.scope_id FOR SHARE;
     IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 original native PRIVATE job required'; END IF;
     SELECT c.* INTO private_control FROM tutor_item_supply_private_job_controls c WHERE c.job_id=private_job.id
      AND c.user_id=NEW.user_id AND c.epoch=NEW.epoch AND c.scope_id=NEW.scope_id FOR SHARE;
     IF NOT FOUND OR private_control.state IS DISTINCT FROM 'leased'
      OR private_control.lease_owner IS DISTINCT FROM private_lease->>'lease_owner'
      OR private_control.lease_generation::text IS DISTINCT FROM private_lease->>'generation'
      OR COALESCE(private_control.state_version>=(private_lease->>'state_version')::bigint,false) IS DISTINCT FROM true
      OR private_control.parent_deadline IS DISTINCT FROM (private_lease->>'parent_deadline')::timestamptz
      OR (private_lease->>'expires_at')::timestamptz>private_control.lease_expires_at
      OR jsonb_typeof(private_lease->'generation') IS DISTINCT FROM 'number' OR jsonb_typeof(private_lease->'state_version') IS DISTINCT FROM 'number'
      OR COALESCE(private_lease->>'expires_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
      OR COALESCE(private_lease->>'parent_deadline' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
      OR COALESCE(p->>'valid_until' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
     THEN RAISE check_violation USING MESSAGE='523 original current PRIVATE lease identity required'; END IF;
     private_profile:=CASE WHEN private_control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
      THEN private_control.profile_snapshot_json->'profile' ELSE private_control.profile_snapshot_json END;
     IF private_profile IS DISTINCT FROM private_lease->'profile'
      OR (CASE WHEN private_control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
        THEN private_control.profile_snapshot_json->'retry_policy' ELSE 'null'::jsonb END) IS DISTINCT FROM private_lease->'retry_policy'
     THEN RAISE check_violation USING MESSAGE='523 exact original PRIVATE profile/retry frame required'; END IF;
     PERFORM id FROM tutor_item_supply_private_budget_roots WHERE id=private_job.root_id AND user_id=NEW.user_id
      AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR SHARE;
     IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 exact original PRIVATE root required'; END IF;
     SELECT * INTO parent FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=NEW.pack_task_id
      AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1' ORDER BY created_at,id LIMIT 1 FOR SHARE;
     IF FOUND AND parent.payload_json->>'root_id' IS DISTINCT FROM p->>'root_id'
     THEN RAISE check_violation USING MESSAGE='523 native PRIVATE task canonical root fixed'; END IF;
     -- This is a real installed native mapping/source receiver, not storage existence.
     PERFORM item_supply_internal.private_native_mapping_current((private_ref->>'mapping_receipt_id')::uuid,NEW.user_id,NEW.epoch::bigint);
     PERFORM m.id FROM tutor_item_supply_finite_course_mappings m,
      LATERAL jsonb_array_elements(m.receipt_json->'pack_request'->'demands') d WHERE m.id=(private_ref->>'mapping_receipt_id')::uuid
      AND m.user_id=NEW.user_id AND m.epoch=NEW.epoch AND d->>'slot'=private_ref->>'slot'
      AND d->>'storage_scope_id'=private_ref->>'goal_scope_id' FOR SHARE OF m;
     IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 native PRIVATE exact current role goal scope required'; END IF;
     stamp:=clock_timestamp();
     IF (p->>'valid_until')::timestamptz>LEAST(private_control.lease_expires_at,private_control.parent_deadline,
        (private_lease->>'expires_at')::timestamptz,(private_lease->>'parent_deadline')::timestamptz)
      OR (p->>'valid_until')::timestamptz>private_control.parent_deadline
      OR (p->>'valid_until')::timestamptz>(private_profile->>'bound_at')::timestamptz+
        (private_profile->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond'
      OR COALESCE((p->>'valid_until')::timestamptz>stamp,false) IS DISTINCT FROM true
     THEN RAISE check_violation USING MESSAGE='523 native PRIVATE deadline/frame expired or extended'; END IF;
    ELSE
     RAISE check_violation USING MESSAGE='523 native PRIVATE phase protocol unsupported';
    END IF;
   ELSIF NEW.record_kind IN('pause','stop') THEN
    IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','reason']) IS DISTINCT FROM true
     OR p->>'schema_version' IS DISTINCT FROM 'persistent_private_stop_v1' OR p->>'reason' IS DISTINCT FROM 'user_stop'
    THEN RAISE check_violation USING MESSAGE='523 closed private stop required'; END IF;
   END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF NEW.record_kind='task' THEN
  IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','public_task_id','intent_hash','target_id','target_definition_hash','public_slots']) IS DISTINCT FROM true
   OR p->>'schema_version' IS DISTINCT FROM 'persistent_public_task_v1' OR (p->>'public_task_id')::uuid IS DISTINCT FROM NEW.public_task_id
   OR COALESCE(p->>'target_id' IN('python-kc-binding-v1','python-state-update-v1','sqlite-predicate-order-v1'),false) IS DISTINCT FROM true
   OR jsonb_typeof(p->'public_slots') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'public_slots') IS DISTINCT FROM 5
   OR COALESCE(p->>'intent_hash' ~ '^[0-9a-f]{64}$',false) IS DISTINCT FROM true
   OR COALESCE(p->>'target_definition_hash' ~ '^[0-9a-f]{64}$',false) IS DISTINCT FROM true
   OR NEW.root_id IS NOT NULL OR NEW.job_id IS NOT NULL OR NEW.phase_id IS NOT NULL
  THEN RAISE check_violation USING MESSAGE='523 closed public finite task required'; END IF;
  IF (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p->'public_slots'))<>5
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'public_slots') v WHERE jsonb_typeof(v) IS DISTINCT FROM 'string'
    OR COALESCE((v#>>'{}') ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true)
  THEN RAISE check_violation USING MESSAGE='523 five unique public slots required'; END IF;
 ELSE
  SELECT * INTO header FROM tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=NEW.public_task_id AND record_kind='task' FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 public original task required'; END IF;
  IF NEW.record_kind IN('version','qualified') THEN
   IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','public_task_id','public_slot_id','slot','revision_id','revision_seq','parent_revision_id','candidate_id','specification','root_id','artifact_id','published_version_id']) IS DISTINCT FROM true
    OR p->>'schema_version' IS DISTINCT FROM 'persistent_public_version_v1' OR (p->>'public_task_id')::uuid IS DISTINCT FROM NEW.public_task_id
    OR (p->>'root_id')::uuid IS DISTINCT FROM NEW.root_id OR NEW.root_id IS NULL OR NEW.job_id IS NOT NULL OR NEW.phase_id IS NOT NULL
    OR COALESCE(p->>'slot'=ANY(slots),false) IS DISTINCT FROM true
    OR COALESCE((p->>'revision_seq')::integer>=1,false) IS DISTINCT FROM true
    OR COALESCE(p->>'revision_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
    OR jsonb_typeof(p->'revision_seq') IS DISTINCT FROM 'number'
    OR item_supply_internal.snapshot_keys(p->'specification',ARRAY['schema_version','target_id','target_definition_hash','family_definition_hash','allocation','seed','blueprint','public_template','coverage_blueprint','python_goal','sql_target']) IS DISTINCT FROM true
   THEN RAISE check_violation USING MESSAGE='523 closed public version required'; END IF;
   slot_index:=array_position(slots,p->>'slot')-1;
   IF p->'public_slot_id' IS DISTINCT FROM header.payload_json->'public_slots'->slot_index
    OR p->'specification'->>'schema_version' IS DISTINCT FROM 'finite_candidate_spec_v1'
    OR p->'specification'->>'target_id' IS DISTINCT FROM header.payload_json->>'target_id'
    OR p->'specification'->>'target_definition_hash' IS DISTINCT FROM header.payload_json->>'target_definition_hash'
    -- A stable pack position is not a historical factory variant identity.
    -- Adopt an unchanged current member of the same original purpose role.
    OR p->'specification'->'allocation'->>'slot' IS DISTINCT FROM
      (CASE WHEN p->>'slot' IN('practice-1','practice-2') THEN 'practice'
       WHEN p->>'slot' IN('assessment-1','assessment-2') THEN 'assessment' ELSE 'remediation' END)
    OR p->'specification'->'coverage_blueprint'->'scope'->>'visibility' IS DISTINCT FROM 'public'
    OR p->'specification'->'coverage_blueprint'->'scope'->>'owner_ref' IS NOT NULL
   THEN RAISE check_violation USING MESSAGE='523 slot original public specification mismatch'; END IF;
   SELECT a.* INTO artifact FROM tutor_item_supply_shared_generation_artifacts a WHERE a.id=(p->>'artifact_id')::uuid
    AND a.root_id=NEW.root_id AND a.candidate_id=(p->>'candidate_id')::uuid FOR SHARE;
   IF NOT FOUND OR item_supply_internal.controlled_counterexample_held(artifact.job_id) IS DISTINCT FROM false
    OR artifact.target_id IS DISTINCT FROM p->'specification'->>'target_id'
    OR artifact.target_definition_hash IS DISTINCT FROM p->'specification'->>'target_definition_hash'
    OR artifact.request_json->'blueprint' IS DISTINCT FROM p->'specification'->'blueprint'
    OR artifact.request_json->'public_template' IS DISTINCT FROM p->'specification'->'public_template'
    OR artifact.request_json->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'specification'->'coverage_blueprint'->'scope')
   THEN RAISE check_violation USING MESSAGE='523 genuine original candidate artifact specification required'; END IF;
   IF artifact.id='4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3' THEN
    committed_child_data:=item_supply_internal.committed_child_version_data_matches(p);
   END IF;
   -- Entire nested specification must equal the original issued validation DATA,
   -- or (qualified adoption) its immutable publication's exact full-spec hash.
   IF NEW.record_kind='qualified' THEN
    SELECT n.* INTO proof FROM tutor_learning_item_native_publication_proofs n WHERE n.version_id=(p->>'published_version_id')::uuid
     AND n.generation_artifact_id=artifact.id AND n.proof_json->>'specification_hash'=item_supply_internal.snapshot_hash(p->'specification') FOR SHARE;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 genuine full-spec original publication required'; END IF;
   ELSE
    IF p->>'published_version_id' IS NOT NULL THEN RAISE check_violation USING MESSAGE='523 unqualified version cannot declare publication'; END IF;
    PERFORM id FROM tutor_item_supply_shared_validation_preparations WHERE generation_artifact_id=artifact.id
     AND payload_json->'spec' IS NOT DISTINCT FROM p->'specification' FOR SHARE;
    IF NOT FOUND AND NOT committed_child_data THEN RAISE check_violation USING MESSAGE='523 original full-spec validation preparation required'; END IF;
   END IF;
   IF (p->>'revision_seq')::integer>1 THEN
    SELECT payload_json INTO parent FROM tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=NEW.public_task_id
     AND record_kind IN('version','qualified') AND payload_json->>'revision_id'=p->>'parent_revision_id' ORDER BY created_at DESC LIMIT 1 FOR SHARE;
    IF NOT FOUND OR parent.payload_json->>'public_slot_id' IS DISTINCT FROM p->>'public_slot_id'
     OR parent.payload_json->>'root_id' IS DISTINCT FROM p->>'root_id'
     OR (parent.payload_json->>'revision_seq')::integer+1 IS DISTINCT FROM (p->>'revision_seq')::integer
     OR parent.payload_json->'specification'->>'seed' IS DISTINCT FROM p->'specification'->>'seed'
     OR (parent.payload_json->'specification'->'allocation' IS DISTINCT FROM p->'specification'->'allocation'
       AND NOT committed_child_data AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations rp
         WHERE rp.candidate_id=artifact.candidate_id AND rp.child_job_id=artifact.job_id
           AND rp.parent_artifact_id=(parent.payload_json->>'artifact_id')::uuid
           AND rp.payload_json->'context'->'persistent_family_revision'->'child_specification'=p->'specification'
           AND item_supply_internal.persistent_registered_family_revision_matches(rp.payload_json)))
    THEN RAISE check_violation USING MESSAGE='523 immutable same-slot root lineage required'; END IF;
    PERFORM id FROM tutor_item_supply_shared_revision_preparations rp WHERE rp.candidate_id=artifact.candidate_id
     AND rp.child_job_id=artifact.job_id AND rp.parent_artifact_id=(parent.payload_json->>'artifact_id')::uuid FOR SHARE;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='523 original same-item substantive revision required'; END IF;
   ELSIF p->>'parent_revision_id' IS NOT NULL OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal
    WHERE public_task_id=NEW.public_task_id AND record_kind IN('version','qualified') AND payload_json->>'public_slot_id'=p->>'public_slot_id'
     AND payload_json->>'revision_id' IS DISTINCT FROM p->>'revision_id') THEN
    RAISE check_violation USING MESSAGE='523 initial slot cannot be replaced';
   END IF;
  ELSIF NEW.record_kind='phase' THEN
   IF NEW.public_task_id IS DISTINCT FROM (p->>'public_task_id')::uuid OR NEW.phase_id IS DISTINCT FROM (p->>'phase_id')::uuid
    OR NEW.job_id IS DISTINCT FROM (p->>'job_id')::uuid OR NEW.root_id IS DISTINCT FROM (p->>'root_id')::uuid
    OR NEW.operation_key IS DISTINCT FROM p->>'operation_key'
   THEN RAISE check_violation USING MESSAGE='523 exact phase journal binding required'; END IF;
   PERFORM item_supply_internal.assert_persistent_pack_phase(p);
  ELSE
   SELECT * INTO phase FROM tutor_item_supply_shared_persistent_pack_journal WHERE phase_id=NEW.phase_id AND record_kind='phase' FOR SHARE;
   IF NOT FOUND OR phase.public_task_id IS DISTINCT FROM NEW.public_task_id OR phase.root_id IS DISTINCT FROM NEW.root_id OR phase.job_id IS DISTINCT FROM NEW.job_id
    THEN RAISE check_violation USING MESSAGE='523 stage original phase required'; END IF;
   IF NEW.record_kind='dispatch_started' THEN
    IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','phase_id']) IS DISTINCT FROM true
     OR p->>'schema_version' IS DISTINCT FROM 'persistent_dispatch_started_v1' OR (p->>'phase_id')::uuid IS DISTINCT FROM NEW.phase_id
     OR NEW.operation_key IS DISTINCT FROM phase.operation_key
    THEN RAISE check_violation USING MESSAGE='523 exact dispatch schema required'; END IF;
   ELSIF NEW.record_kind IN('stage_started','stage_result') THEN
    IF (CASE WHEN NEW.record_kind='stage_started' THEN item_supply_internal.snapshot_keys(p,ARRAY['schema_version','phase_id','stage','operation_key'])
      ELSE item_supply_internal.snapshot_keys(p,ARRAY['schema_version','phase_id','stage','operation_key','outcome','receipt_id','safe_reason']) END) IS DISTINCT FROM true
     OR p->>'schema_version' IS DISTINCT FROM (CASE WHEN NEW.record_kind='stage_started' THEN 'persistent_stage_started_v1' ELSE 'persistent_stage_result_v1' END)
     OR (p->>'phase_id')::uuid IS DISTINCT FROM NEW.phase_id OR p->>'operation_key' IS DISTINCT FROM NEW.operation_key
     OR COALESCE(p->>'stage' IN('author','validation','review','investigation','revision','recheck','facts','publication','relation'),false) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='523 closed original stage required'; END IF;
    IF NEW.record_kind='stage_result' AND (
     COALESCE(p->>'outcome' IN('completed','qualified','failed','blocked','outcome_unknown'),false) IS DISTINCT FROM true
     OR COALESCE(p->>'safe_reason' ~ '^[a-z0-9_]{1,160}$',false) IS DISTINCT FROM true
     OR (p->'receipt_id' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(p->'receipt_id') IS DISTINCT FROM 'string'
      OR COALESCE(p->>'receipt_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true)))
    THEN RAISE check_violation USING MESSAGE='523 closed stage result scalar DATA required'; END IF;
   ELSIF NEW.record_kind='phase_result' THEN
    IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','phase_id','status','safe_reason','artifact_id','published_version_id','relation_receipt_id','usage_state']) IS DISTINCT FROM true
     OR p->>'schema_version' IS DISTINCT FROM 'persistent_phase_outcome_v1' OR (p->>'phase_id')::uuid IS DISTINCT FROM NEW.phase_id
     OR NEW.operation_key IS DISTINCT FROM phase.operation_key
     OR COALESCE(p->>'status' IN('qualified','quality_failed','blocked','outcome_unknown','relation_ready'),false) IS DISTINCT FROM true
     OR COALESCE(p->>'safe_reason' ~ '^[a-z0-9_]{1,160}$',false) IS DISTINCT FROM true
     OR COALESCE(p->>'usage_state' IN('known','unknown'),false) IS DISTINCT FROM true
     OR p->'relation_receipt_id' IS DISTINCT FROM 'null'::jsonb
     OR (p->'artifact_id' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(p->'artifact_id') IS DISTINCT FROM 'string'
      OR COALESCE(p->>'artifact_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true))
     OR (p->'published_version_id' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(p->'published_version_id') IS DISTINCT FROM 'string'
      OR COALESCE(p->>'published_version_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true))
    THEN RAISE check_violation USING MESSAGE='523 closed original outcome required'; END IF;
   END IF;
   IF NEW.record_kind IN('dispatch_started','stage_started') THEN
    PERFORM item_supply_internal.assert_persistent_pack_phase(phase.payload_json);
    IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal WHERE phase_id=NEW.phase_id AND record_kind='phase_result')
    THEN RAISE check_violation USING MESSAGE='523 terminal phase cannot dispatch'; END IF;
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $body546$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_persistent_pack_journal_insert() FROM PUBLIC;
DO $post546$ BEGIN
 IF encode(sha256(convert_to((SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure('item_supply_internal.enforce_persistent_pack_journal_insert()')),'UTF8')),'hex') IS DISTINCT FROM '5ace67de112f22687c435cbfa432237464832fb735ef04880bb570c5f97003ba'
 THEN RAISE check_violation USING MESSAGE='546 installed exact body mismatch'; END IF;
END $post546$;

DO $pre546$ DECLARE actual record; BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='546 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('public.enforce_item_supply_shared_candidate_continuation()');
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='546 installed prior receiver required'; END IF;
 IF FOUND AND (encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') NOT IN ('08ed45d7d088992ba6d9e9ee6d3db0745509dc4f39f1dfca98ffa69aa1106191','368c07a1950a76d042fb9fa142620e4c9ccec37ccb5597fa185f424207a55ca1')
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR actual.lanname<>'plpgsql'
   OR actual.prokind<>'f' OR NOT actual.prosecdef OR actual.proretset OR actual.proisstrict OR actual.proleakproof
   OR actual.provolatile<>'v' OR actual.proparallel<>'u' OR actual.prorettype<>to_regtype('pg_catalog.trigger')
   OR actual.pronargdefaults<>0 OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'])
 THEN RAISE check_violation USING MESSAGE='546 exact prior/new body and metadata required: public.enforce_item_supply_shared_candidate_continuation()'; END IF;
END $pre546$;
CREATE OR REPLACE FUNCTION public.enforce_item_supply_shared_candidate_continuation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body546$
DECLARE a record; c record; root_facts record; t timestamptz; snapshot jsonb; b jsonb:=NEW.binding_json;
  phase_row record; version_row record; private_header record; phase jsonb;
  stage_key text; persistent_permission boolean:=false;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared continuation B1d owner required';
  END IF;
  SELECT c1.*,j.root_id,j.parent_job_id,j.job_key,p.profile_hash,p.profile_json INTO c
    FROM tutor_item_supply_shared_job_controls c1 JOIN tutor_item_supply_shared_jobs j ON j.id=c1.job_id
    JOIN tutor_item_supply_parameter_profiles p ON p.id=c1.profile_id
    WHERE c1.job_id=NEW.job_id FOR UPDATE OF c1;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='continuation job unavailable'; END IF;
  stage_key:='continue.'||replace(NEW.generation_artifact_id::text,'-','')||'.'||NEW.operation_key;
  IF NEW.operation_key LIKE 'persistent.%' AND c.job_key IS DISTINCT FROM encode(digest(convert_to(
      NEW.root_id::text||chr(31)||stage_key,'UTF8'),'sha256'),'hex') THEN
    -- Controlled ancestry wins BEFORE looking for any normal phase permission.
    PERFORM id FROM tutor_item_supply_shared_generation_artifacts
      WHERE id=NEW.generation_artifact_id AND root_id=NEW.root_id
        AND item_supply_internal.controlled_counterexample_held(job_id) IS FALSE FOR SHARE;
    IF NOT FOUND OR item_supply_internal.controlled_counterexample_held(NEW.job_id) IS DISTINCT FROM false
    THEN RAISE check_violation USING MESSAGE='528 controlled ancestry denied first'; END IF;
    IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off'
      OR item_supply_internal.snapshot_keys(b,ARRAY['schema_version','operation_key','root_id','canonical_root_key',
        'coverage_blueprint_hash','scope_hash','generation_artifact_id','original_job_id','original_lease_generation',
        'original_profile_hash','artifact_hash','original_request_hash','material_set_hash','source_receipt_set_hash',
        'candidate_id','item_id','version_id','source_hash','content_hash','target_id','target_definition_hash',
        'specification_hash','adoption_lease','authority','execution_authority_reusable','publication_enabled']) IS DISTINCT FROM true
      OR b->>'schema_version' IS DISTINCT FROM 'shared_candidate_continuation_v1'
    THEN RAISE check_violation USING MESSAGE='528 closed original binding and read-write phase required'; END IF;
    IF (SELECT count(*) FROM tutor_item_supply_shared_persistent_pack_journal j
      WHERE j.record_kind='phase' AND j.job_id=NEW.job_id AND j.root_id=NEW.root_id
        AND NEW.operation_key='persistent.'||replace(j.phase_id::text,'-',''))<>1
    THEN RAISE check_violation USING MESSAGE='528 unique original candidate phase required'; END IF;
    SELECT j.* INTO phase_row FROM tutor_item_supply_shared_persistent_pack_journal j
      WHERE j.record_kind='phase' AND j.job_id=NEW.job_id AND j.root_id=NEW.root_id
        AND NEW.operation_key='persistent.'||replace(j.phase_id::text,'-','') FOR SHARE;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='528 committed original candidate phase required'; END IF;
    phase:=phase_row.payload_json;
    PERFORM item_supply_internal.assert_persistent_pack_phase(phase);
    IF phase->>'kind' IS DISTINCT FROM 'candidate' OR phase->>'job_id' IS DISTINCT FROM NEW.job_id::text
      OR phase->>'root_id' IS DISTINCT FROM NEW.root_id::text
      OR phase->>'phase_id' IS DISTINCT FROM phase_row.phase_id::text
      OR phase->>'public_task_id' IS DISTINCT FROM phase_row.public_task_id::text
      OR phase->'lease' IS DISTINCT FROM b->'adoption_lease'
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j
        WHERE j.phase_id=phase_row.phase_id AND j.record_kind='phase_result')
    THEN RAISE check_violation USING MESSAGE='528 exact active candidate phase lease required'; END IF;
    SELECT j.* INTO version_row FROM tutor_item_supply_shared_persistent_pack_journal j
      WHERE j.public_task_id=phase_row.public_task_id AND j.record_kind IN('version','qualified')
        AND j.payload_json->>'revision_id'=phase->>'revision_id'
      ORDER BY j.created_at DESC,j.id LIMIT 1 FOR SHARE;
    IF NOT FOUND OR version_row.root_id IS DISTINCT FROM NEW.root_id
      OR version_row.payload_json->>'artifact_id' IS DISTINCT FROM NEW.generation_artifact_id::text
      OR version_row.payload_json->'public_slot_id' IS DISTINCT FROM phase->'public_slot_id'
      OR version_row.payload_json->>'root_id' IS DISTINCT FROM NEW.root_id::text
      OR b->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(version_row.payload_json->'specification')
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j
        WHERE j.public_task_id=phase_row.public_task_id AND j.record_kind IN('version','qualified')
          AND j.payload_json->'public_slot_id'=phase->'public_slot_id'
          AND (j.payload_json->>'revision_seq')::integer>(version_row.payload_json->>'revision_seq')::integer)
    THEN RAISE check_violation USING MESSAGE='528 exact current fixed-slot immutable artifact required'; END IF;
    IF (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j
      JOIN tutor_item_supply_private_persistent_pack_journal attachment ON attachment.pack_task_id=j.pack_task_id
        AND attachment.user_id=j.user_id AND attachment.epoch=j.epoch AND attachment.scope_id=j.scope_id
        AND attachment.record_kind='phase'
        AND attachment.payload_json->>'schema_version'='persistent_private_phase_attachment_v1'
        AND attachment.payload_json->>'phase_id'=phase_row.phase_id::text
        AND attachment.payload_json->>'public_task_id'=phase_row.public_task_id::text
      WHERE j.record_kind='task' AND j.id=j.pack_task_id
        AND j.payload_json->'ref'->>'public_task_id'=phase_row.public_task_id::text)<>1
    THEN RAISE check_violation USING MESSAGE='528 unique original private phase attachment required'; END IF;
    SELECT j.* INTO private_header FROM tutor_item_supply_private_persistent_pack_journal j
      JOIN tutor_item_supply_private_persistent_pack_journal attachment ON attachment.pack_task_id=j.pack_task_id
        AND attachment.user_id=j.user_id AND attachment.epoch=j.epoch AND attachment.scope_id=j.scope_id
        AND attachment.record_kind='phase'
        AND attachment.payload_json->>'schema_version'='persistent_private_phase_attachment_v1'
        AND attachment.payload_json->>'phase_id'=phase_row.phase_id::text
        AND attachment.payload_json->>'public_task_id'=phase_row.public_task_id::text
      WHERE j.record_kind='task' AND j.id=j.pack_task_id
        AND j.payload_json->'ref'->>'public_task_id'=phase_row.public_task_id::text FOR SHARE OF j,attachment;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='528 original private task attachment required'; END IF;
    IF NEW.generation_artifact_id='4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3' THEN
      IF item_supply_internal.committed_child_version_data_matches(version_row.payload_json) IS DISTINCT FROM true
        OR private_header.pack_task_id IS DISTINCT FROM '6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid
      THEN RAISE check_violation USING MESSAGE='546 exact committed child current source/mapping required'; END IF;
    ELSE
      PERFORM item_supply_internal.public_normal_mapping_current(
        (private_header.payload_json->'ref'->>'mapping_receipt_id')::uuid,private_header.user_id,private_header.epoch::bigint);
    END IF;
    persistent_permission:=true;
    stage_key:='persistent.phase.'||replace(phase_row.phase_id::text,'-','');
  END IF;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  t:=clock_timestamp();
  IF c.state<>'leased' OR c.root_id<>NEW.root_id OR c.parent_job_id IS NOT NULL
    OR c.lease_owner IS DISTINCT FROM b->'adoption_lease'->>'lease_owner'
    OR c.lease_generation::text IS DISTINCT FROM b->'adoption_lease'->>'generation'
    OR c.state_version::text IS DISTINCT FROM b->'adoption_lease'->>'state_version'
    OR c.lease_expires_at IS NULL OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR snapshot IS DISTINCT FROM b->'adoption_lease'->'profile'
    OR c.profile_hash IS DISTINCT FROM snapshot->>'profile_hash'
    OR c.job_key IS DISTINCT FROM encode(digest(convert_to(NEW.root_id::text||chr(31)||
        stage_key,'UTF8'),'sha256'),'hex') THEN
    RAISE check_violation USING MESSAGE='continuation current new-job lease mismatch';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR a.root_id<>NEW.root_id THEN
    RAISE check_violation USING MESSAGE='continuation must retain original canonical root';
  END IF;
  SELECT r.canonical_key,bp.blueprint_hash,o.provider_key INTO root_facts
    FROM tutor_item_supply_shared_budget_roots r JOIN tutor_item_supply_shared_blueprints bp ON bp.id=r.blueprint_id
    JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id WHERE r.id=NEW.root_id FOR SHARE OF r,bp,o;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='continuation root unavailable'; END IF;
  IF b->>'root_id' IS DISTINCT FROM NEW.root_id::text OR b->>'generation_artifact_id' IS DISTINCT FROM a.id::text
    OR b->>'original_job_id' IS DISTINCT FROM a.job_id::text
    OR b->>'original_lease_generation' IS DISTINCT FROM a.lease_generation::text
    OR b->>'candidate_id' IS DISTINCT FROM a.candidate_id::text OR b->>'item_id' IS DISTINCT FROM a.item_id::text
    OR b->>'version_id' IS DISTINCT FROM a.version_id::text OR b->>'source_hash' IS DISTINCT FROM a.source_hash
    OR b->>'content_hash' IS DISTINCT FROM a.content_hash OR b->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR b->>'target_id' IS DISTINCT FROM a.target_id OR b->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR b->>'operation_key' IS DISTINCT FROM NEW.operation_key
    OR b->>'canonical_root_key' IS DISTINCT FROM root_facts.canonical_key
    OR b->>'coverage_blueprint_hash' IS DISTINCT FROM root_facts.blueprint_hash
    OR b->>'scope_hash' IS DISTINCT FROM a.request_json->>'scope_hash'
    OR b->>'original_profile_hash' IS DISTINCT FROM a.request_json->'profile'->>'profile_hash'
    OR b->>'original_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json)
    OR b->>'material_set_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json->'materials')
    OR b->>'source_receipt_set_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.receipt_json->'sources')
    OR b->'adoption_lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR b->'adoption_lease'->>'visibility' IS DISTINCT FROM 'public'
    OR b->'adoption_lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb
    OR b->'adoption_lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
    OR snapshot->>'profile_key_hash' IS DISTINCT FROM a.request_json->'profile'->>'profile_key_hash'
    OR c.profile_json->'profile_key'->>'provider' IS DISTINCT FROM root_facts.provider_key
    OR a.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
    OR b->>'authority' IS DISTINCT FROM 'immutable_generation_data_only'
    OR b->'execution_authority_reusable' IS DISTINCT FROM 'false'::jsonb
    OR b->'publication_enabled' IS DISTINCT FROM 'false'::jsonb THEN
    RAISE check_violation USING MESSAGE='continuation immutable original binding mismatch';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=a.job_id
      AND cp.lease_generation=a.lease_generation AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=a.artifact_hash)
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=a.reservation_id
      AND s.settlement_key='generation.'||replace(a.candidate_id::text,'-','')) THEN
    RAISE check_violation USING MESSAGE='continuation requires complete settled original generation';
  END IF;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts WHERE job_id=NEW.job_id)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints WHERE job_id=NEW.job_id AND stage='generating')
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations WHERE job_id=NEW.job_id AND reservation_key LIKE 'gen.%') THEN
    RAISE check_violation USING MESSAGE='continuation cannot masquerade as new generation';
  END IF;
  IF persistent_permission THEN
    -- No new author permissions: retain complete original491 checks above.
    -- Current source and all real phase deadlines are rechecked AFTER every wait.
    IF version_row.payload_json->'specification'->'blueprint' IS DISTINCT FROM a.request_json->'blueprint'
      OR version_row.payload_json->'specification'->'public_template' IS DISTINCT FROM a.request_json->'public_template'
      OR item_supply_internal.public_native_source_current(jsonb_build_object(
        'request',a.request_json,'ref',private_header.payload_json->'ref')) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='528 original fixed specification/current source required'; END IF;
    PERFORM item_supply_internal.assert_persistent_pack_phase(phase);
    t:=clock_timestamp();
    IF COALESCE(c.lease_expires_at>t,false) IS DISTINCT FROM true OR COALESCE(c.parent_deadline>t,false) IS DISTINCT FROM true
      OR COALESCE((phase->>'valid_until')::timestamptz>t,false) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='528 final acceptance deadline expired'; END IF;
  END IF;
  RETURN NEW;
END $body546$;
REVOKE ALL ON FUNCTION public.enforce_item_supply_shared_candidate_continuation() FROM PUBLIC;
DO $post546$ BEGIN
 IF encode(sha256(convert_to((SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure('public.enforce_item_supply_shared_candidate_continuation()')),'UTF8')),'hex') IS DISTINCT FROM '368c07a1950a76d042fb9fa142620e4c9ccec37ccb5597fa185f424207a55ca1'
 THEN RAISE check_violation USING MESSAGE='546 installed exact body mismatch'; END IF;
END $post546$;

DO $check546$ DECLARE d text; BEGIN
 SELECT pg_get_constraintdef(oid) INTO d FROM pg_constraint WHERE conrelid='public.tutor_item_supply_shared_revision_recheck_preparations'::regclass AND conname='tutor_item_supply_shared_revision_recheck_pr_payload_json_check';
 IF d IS DISTINCT FROM $oldcheck546$CHECK (((jsonb_typeof(payload_json) = 'object'::text) AND (octet_length((payload_json)::text) <= 1048576) AND (NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_preparation_v1'::text))))$oldcheck546$ AND d IS DISTINCT FROM $newcheck546$CHECK (((jsonb_typeof(payload_json) = 'object'::text) AND (octet_length((payload_json)::text) <= 1048576) AND ((NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_preparation_v1'::text)) OR (NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_preparation_v2'::text)))))$newcheck546$
 THEN RAISE check_violation USING MESSAGE='546 exact prior/new closed payload CHECK required'; END IF;
 IF d=$oldcheck546$CHECK (((jsonb_typeof(payload_json) = 'object'::text) AND (octet_length((payload_json)::text) <= 1048576) AND (NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_preparation_v1'::text))))$oldcheck546$ THEN
   ALTER TABLE tutor_item_supply_shared_revision_recheck_preparations DROP CONSTRAINT tutor_item_supply_shared_revision_recheck_pr_payload_json_check;
   ALTER TABLE tutor_item_supply_shared_revision_recheck_preparations ADD CONSTRAINT tutor_item_supply_shared_revision_recheck_pr_payload_json_check CHECK (((jsonb_typeof(payload_json) = 'object'::text) AND (octet_length((payload_json)::text) <= 1048576) AND ((NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_preparation_v1'::text)) OR (NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_preparation_v2'::text)))));
 END IF;
END $check546$;
DO $check546$ DECLARE d text; BEGIN
 SELECT pg_get_constraintdef(oid) INTO d FROM pg_constraint WHERE conrelid='public.tutor_item_supply_shared_revision_recheck_receipts'::regclass AND conname='tutor_item_supply_shared_revision_recheck_re_payload_json_check';
 IF d IS DISTINCT FROM $oldcheck546$CHECK (((jsonb_typeof(payload_json) = 'object'::text) AND (octet_length((payload_json)::text) <= 1048576) AND (NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_receipt_v1'::text))))$oldcheck546$ AND d IS DISTINCT FROM $newcheck546$CHECK (((jsonb_typeof(payload_json) = 'object'::text) AND (octet_length((payload_json)::text) <= 1048576) AND ((NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_receipt_v1'::text)) OR (NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_receipt_v2'::text)))))$newcheck546$
 THEN RAISE check_violation USING MESSAGE='546 exact prior/new closed payload CHECK required'; END IF;
 IF d=$oldcheck546$CHECK (((jsonb_typeof(payload_json) = 'object'::text) AND (octet_length((payload_json)::text) <= 1048576) AND (NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_receipt_v1'::text))))$oldcheck546$ THEN
   ALTER TABLE tutor_item_supply_shared_revision_recheck_receipts DROP CONSTRAINT tutor_item_supply_shared_revision_recheck_re_payload_json_check;
   ALTER TABLE tutor_item_supply_shared_revision_recheck_receipts ADD CONSTRAINT tutor_item_supply_shared_revision_recheck_re_payload_json_check CHECK (((jsonb_typeof(payload_json) = 'object'::text) AND (octet_length((payload_json)::text) <= 1048576) AND ((NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_receipt_v1'::text)) OR (NOT ((payload_json ->> 'schema_version'::text) IS DISTINCT FROM 'native_shared_revision_recheck_receipt_v2'::text)))));
 END IF;
END $check546$;

