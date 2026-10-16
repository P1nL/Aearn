-- Normal PUBLIC revision output observations, not provider/review/publication permission.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='541 B1d only'; END IF; END $$;
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_revision_generation_outputs (
 preparation_id uuid PRIMARY KEY REFERENCES tutor_item_supply_shared_revision_preparations(id) ON DELETE RESTRICT,
 root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
 job_id uuid NOT NULL, candidate_id uuid NOT NULL,
 reservation_id uuid NOT NULL UNIQUE, settlement_id uuid NOT NULL REFERENCES tutor_item_supply_shared_runtime_settlements(id) ON DELETE RESTRICT,
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=2097152),
 snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 capture_txid bigint NOT NULL,
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
 FOREIGN KEY(reservation_id,job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT
);
REVOKE ALL ON tutor_item_supply_shared_revision_generation_outputs FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_revision_generation_output_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body541$
DECLARE p tutor_item_supply_shared_revision_preparations%ROWTYPE;
 s tutor_item_supply_shared_runtime_settlements%ROWTYPE;
 r tutor_item_supply_shared_reservations%ROWTYPE;
 d jsonb:=NEW.payload_json; result_data jsonb; provider_data jsonb;
BEGIN
 NEW.capture_txid:=txid_current(); -- TOP XID, including an append inside a savepoint.
 SELECT * INTO p FROM tutor_item_supply_shared_revision_preparations WHERE id=NEW.preparation_id FOR SHARE;
 SELECT * INTO s FROM tutor_item_supply_shared_runtime_settlements WHERE id=NEW.settlement_id FOR SHARE;
 SELECT * INTO r FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id FOR SHARE;
 IF p.id IS NULL OR s.id IS NULL OR r.id IS NULL
  OR item_supply_internal.snapshot_keys(d,ARRAY['schema_version','preparation_id','preparation_hash','lease','request','request_hash',
    'result','returned_state','returned_safe_reason','author_input','evidence_policy_hash','producer_binding','deadline_at']) IS DISTINCT FROM true
  OR d->>'schema_version' IS DISTINCT FROM 'normal_revision_generation_output_v1'
  OR (NEW.root_id,NEW.job_id,NEW.candidate_id) IS DISTINCT FROM (p.root_id,p.child_job_id,p.candidate_id)
  OR (r.root_id,r.job_id,s.reservation_id) IS DISTINCT FROM (NEW.root_id,NEW.job_id,NEW.reservation_id)
  OR d->>'preparation_id' IS DISTINCT FROM p.id::text OR d->>'preparation_hash' IS DISTINCT FROM p.snapshot_hash
  OR d->'request' IS DISTINCT FROM p.payload_json->'request' OR d->>'request_hash' IS DISTINCT FROM p.payload_json->>'request_hash'
  OR d->'lease' IS DISTINCT FROM p.payload_json->'child_lease'
  OR d->>'deadline_at' IS DISTINCT FROM p.payload_json->>'deadline_at'
  OR s.settlement_key IS DISTINCT FROM 'generation.'||replace(NEW.candidate_id::text,'-','')
  OR r.reservation_key IS DISTINCT FROM 'gen.'||replace(NEW.candidate_id::text,'-','')
  OR d->'author_input'->>'schema_version' IS DISTINCT FROM 'native_revision_author_input_binding_v1'
  OR d->'author_input'->>'request_hash' IS DISTINCT FROM d->>'request_hash'
  OR d->'author_input'->>'context_hash' IS DISTINCT FROM p.payload_json->>'context_hash'
  OR jsonb_typeof(d->'author_input'->'input_bytes') IS DISTINCT FROM 'number'
  OR (d->'author_input'->>'input_bytes')::bigint>(d->'request'->'limits'->>'max_input_bytes')::bigint
  OR COALESCE(d->>'returned_state' IN('staged','failed','blocked'),false) IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_receipts ir
   JOIN tutor_item_supply_shared_review_investigation_preparations ip ON ip.id=ir.preparation_id
   WHERE ir.id=p.investigation_receipt_id AND ip.payload_json ? 'persistent_frame')
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations rp WHERE rp.id=p.id AND rp.xmin::text::bigint<>txid_current()%4294967296)
 THEN RAISE check_violation USING MESSAGE='541 original normal revision output/settlement binding required'; END IF;
 result_data:=d->'result'; provider_data:=result_data->'receipt'->'provider';
 IF result_data->>'state' IS DISTINCT FROM 'staged' OR result_data->>'safe_reason' IS DISTINCT FROM 'staged'
  OR jsonb_typeof(result_data->'source') IS DISTINCT FROM 'object' OR jsonb_typeof(result_data->'receipt') IS DISTINCT FROM 'object'
  OR result_data->'receipt'->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
  OR result_data->'receipt'->>'scope_hash' IS DISTINCT FROM d->'request'->>'scope_hash'
  OR result_data->'source'->'blueprint' IS DISTINCT FROM d->'request'->'blueprint'
  OR provider_data->>'mode' IS DISTINCT FROM 'provider'
  OR provider_data->>'model' IS DISTINCT FROM provider_data->>'configured_model'
  OR d->'producer_binding' IS DISTINCT FROM jsonb_build_array(provider_data->>'provider',provider_data->>'configured_model')
  OR (s.usage_state='known' AND s.receipt_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(provider_data))
  OR s.usage_state NOT IN('known','unknown')
 THEN RAISE check_violation USING MESSAGE='541 full original staged output and provider receipt required'; END IF;
 -- Capture may outlive a fence: preserve observed output/fees as DATA. Recovery rechecks current authority.
 RETURN NEW;
END $body541$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_revision_generation_output_insert() FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_revision_generation_output_current(output_preparation uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body541$
DECLARE o tutor_item_supply_shared_revision_generation_outputs%ROWTYPE;
 p tutor_item_supply_shared_revision_preparations%ROWTYPE;
 ip tutor_item_supply_shared_review_investigation_preparations%ROWTYPE;
 c tutor_item_supply_shared_job_controls%ROWTYPE;
 pc tutor_item_supply_shared_job_controls%ROWTYPE;
 fresh boolean; stamp timestamptz; bound jsonb;
BEGIN
 SELECT * INTO o FROM tutor_item_supply_shared_revision_generation_outputs WHERE preparation_id=output_preparation FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='GENERATION_DURABLE_BINDING_MISSING'; END IF;
 IF o.capture_txid=txid_current()
 THEN RAISE check_violation USING MESSAGE='GENERATION_DURABLE_BINDING_NOT_COMMITTED'; END IF;
 SELECT * INTO p FROM tutor_item_supply_shared_revision_preparations WHERE id=o.preparation_id FOR SHARE;
 SELECT ipr.* INTO ip FROM tutor_item_supply_shared_review_investigation_preparations ipr
  JOIN tutor_item_supply_shared_review_investigation_receipts ir ON ir.preparation_id=ipr.id WHERE ir.id=p.investigation_receipt_id FOR SHARE OF ipr;
 SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=p.child_job_id FOR SHARE;
 SELECT * INTO pc FROM tutor_item_supply_shared_job_controls WHERE job_id=p.parent_job_id FOR SHARE;
 IF p.id IS NULL OR ip.id IS NULL OR c.id IS NULL OR pc.id IS NULL OR NOT (ip.payload_json ? 'persistent_frame')
  OR o.payload_json->>'returned_state' IS DISTINCT FROM 'staged'
  OR o.payload_json->>'preparation_hash' IS DISTINCT FROM p.snapshot_hash
  OR item_supply_internal.controlled_counterexample_held(c.job_id) IS DISTINCT FROM false
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.id=o.settlement_id
    AND s.reservation_id=o.reservation_id AND s.xmin::text::bigint<>txid_current()%4294967296)
 THEN RAISE check_violation USING MESSAGE='541 normal committed output persistence scope required'; END IF;
 fresh:=item_supply_internal.fresh_committed_revision_matches(p.payload_json);
 IF NOT fresh THEN PERFORM item_supply_internal.assert_persistent_normal_repair(ip.payload_json); END IF;
 stamp:=clock_timestamp();
 IF p.valid_until<=stamp OR c.state IS DISTINCT FROM 'leased' OR pc.state IS DISTINCT FROM 'leased'
  OR c.lease_expires_at IS NULL OR c.lease_expires_at<=stamp OR c.parent_deadline<=stamp
  OR pc.lease_expires_at IS NULL OR pc.lease_expires_at<=stamp OR pc.parent_deadline<=stamp
  OR c.lease_owner IS DISTINCT FROM o.payload_json->'lease'->>'lease_owner'
  OR c.lease_generation::text IS DISTINCT FROM o.payload_json->'lease'->>'generation'
  OR c.state_version<(o.payload_json->'lease'->>'state_version')::bigint
  OR (CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1' THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END)
    IS DISTINCT FROM o.payload_json->'lease'->'profile'
 THEN RAISE check_violation USING MESSAGE='541 current original persistence lease/deadline required'; END IF;
 FOR bound IN SELECT value FROM jsonb_array_elements(p.payload_json->'source_deadlines') LOOP
  IF COALESCE((bound->>'retained_until')::timestamptz>stamp,false) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='541 persistence source expired'; END IF;
 END LOOP;
END $body541$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_revision_generation_output_current(uuid) FROM PUBLIC;
DROP TRIGGER IF EXISTS revision_generation_output_insert ON tutor_item_supply_shared_revision_generation_outputs;
CREATE TRIGGER revision_generation_output_insert BEFORE INSERT ON tutor_item_supply_shared_revision_generation_outputs
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_revision_generation_output_insert();
DROP TRIGGER IF EXISTS revision_generation_output_immutable ON tutor_item_supply_shared_revision_generation_outputs;
CREATE TRIGGER revision_generation_output_immutable BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_revision_generation_outputs
 FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');
