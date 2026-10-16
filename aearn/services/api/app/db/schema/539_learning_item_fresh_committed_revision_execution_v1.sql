--539 fixed committed investigation DATA -> new same-root original517 revision execution.
-- No ordinary phase, old-time renewal, investigation replay, history mutation or public grant.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_user<>'aearn_b1d_runtime_20261001' THEN RAISE check_violation USING MESSAGE='539 exact sandbox owner required'; END IF; END $$;

DO $guard539$ DECLARE a record; BEGIN SELECT p.*,l.lanname INTO a FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_committed_revision_execution(jsonb)');
 IF FOUND AND (encode(sha256(convert_to(a.prosrc,'UTF8')),'hex') IS DISTINCT FROM 'c831377e715515e9c55e29492025d5e3011654b455d04c74fd49295ed63f2eaa'
  OR a.proargnames IS DISTINCT FROM ARRAY['p']::text[] OR a.prorettype IS DISTINCT FROM 'pg_catalog.void'::regtype
  OR a.lanname<>'plpgsql' OR a.prokind<>'f' OR NOT a.prosecdef OR a.proretset OR a.proisstrict OR a.proleakproof
  OR a.provolatile<>'v' OR a.proparallel<>'u' OR a.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR a.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR a.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR a.proallargtypes IS NOT NULL OR a.proargmodes IS NOT NULL OR a.provariadic<>0 OR a.pronargdefaults<>0
  OR a.procost<>100 OR a.prorows<>0 OR a.prosupport<>0 OR a.proargdefaults IS NOT NULL OR a.probin IS NOT NULL OR a.prosqlbody IS NOT NULL)
 THEN RAISE check_violation USING MESSAGE='539 unexpected existing receiver'; END IF; END $guard539$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_committed_revision_execution(p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body539$
DECLARE h tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 ip tutor_item_supply_shared_review_investigation_preparations%ROWTYPE;
 ir tutor_item_supply_shared_review_investigation_receipts%ROWTYPE;
 a tutor_item_supply_shared_generation_artifacts%ROWTYPE;
 j tutor_item_supply_shared_jobs%ROWTYPE; c tutor_item_supply_shared_job_controls%ROWTYPE;
 b tutor_item_supply_development_model_accounting_batches%ROWTYPE;
 m tutor_item_supply_development_model_accounting_jobs%ROWTYPE;
 expected record; digest text; lease_data jsonb; snapshot jsonb; bound jsonb; stamp timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('session_replication_role')<>'origin'
 THEN RAISE check_violation USING MESSAGE='539 exact original sandbox required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('fresh-committed-revision'),hashtext('87596016-7639-4ed9-8f05-684b7bf8027c'));
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','authorization_sha256','task_ref','historical_phase_id',
  'investigation_receipt_id','investigation_receipt_hash','investigation_preparation_hash','root_id','execution_job_id',
  'execution_lease','batch_id','profile_hash','source_deadlines','issued_at','valid_until']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'persistent_committed_revision_execution_v1'
  OR p->>'authorization_sha256' IS DISTINCT FROM 'beb3e25f2a11f9fcb6d6bac24d17e143a9909907befc9081ed540c937df72fc1'
  OR p->>'historical_phase_id' IS DISTINCT FROM 'baa4d9d7-411d-452f-acf3-ed9551c12743'
  OR p->>'investigation_receipt_id' IS DISTINCT FROM '87596016-7639-4ed9-8f05-684b7bf8027c'
  OR p->>'investigation_receipt_hash' IS DISTINCT FROM '0a5cd30a9e689b901bba452599c93db1a794367cec7b5069c3f3113215eae4c6'
  OR p->>'investigation_preparation_hash' IS DISTINCT FROM '9f289b161cc69a3bb02eea06e47d329a9ad1ff243d3ca9185801b4eb104ac5a7'
  OR p->>'root_id' IS DISTINCT FROM '7d4b85ba-a0ec-4348-ac11-3401c6bded47'
  OR jsonb_typeof(p->'execution_lease') IS DISTINCT FROM 'object'
  OR COALESCE(p->>'issued_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
  OR COALESCE(p->>'valid_until' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='539 registered closed execution payload required'; END IF;
 SELECT * INTO h FROM tutor_item_supply_private_persistent_pack_journal
  WHERE id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND record_kind='task' FOR SHARE;
 IF NOT FOUND OR h.pack_task_id IS DISTINCT FROM h.id OR h.payload_json->'ref' IS DISTINCT FROM p->'task_ref'
  OR h.payload_hash IS DISTINCT FROM '07e42ce62c1714e093f0e7d5e3ad1928a5da617c8597cfcebce51e7f7ea6b976'
 THEN RAISE check_violation USING MESSAGE='539 exact original PRIVATE task required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current((p->'task_ref'->>'mapping_receipt_id')::uuid,h.user_id,h.epoch);
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=h.id
  AND user_id=h.user_id AND epoch=h.epoch AND record_kind IN('pause','stop'))
 THEN RAISE check_violation USING MESSAGE='539 original task stopped'; END IF;
 FOR expected IN SELECT * FROM (VALUES
  ('tutor_item_supply_private_persistent_pack_journal','4a4dcaf7-de04-4c7c-869b-80cc8cac2758'::uuid,'7373bd119461bf1bc2ca530f246fe050807690034551d3ee1feeb3a02b8588ce'),
  ('tutor_item_supply_private_persistent_pack_journal','4c3979f1-eb90-4f84-b036-344f026dc20b'::uuid,'6cb11d40416d57c0c144e821efa77c097fe2f1f07e5c05f5f63190e120643bcc'),
  ('tutor_item_supply_private_persistent_pack_journal','6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'07e42ce62c1714e093f0e7d5e3ad1928a5da617c8597cfcebce51e7f7ea6b976'),
  ('tutor_item_supply_private_persistent_pack_journal','b8295537-58a0-4301-b22b-af3151bdb2b2'::uuid,'2fca5c397954c2ad626f1c986a150f26790a4254e77987236398559566794cb4'),
  ('tutor_item_supply_private_persistent_pack_journal','cb38b2d6-5667-418d-8c5c-0fe807cb79b4'::uuid,'ef76b8c8ef762498f6b9f88917369a61178058c236069a562b5e4853c04675fa'),
  ('tutor_item_supply_private_persistent_pack_journal','d37ac9bb-4903-4a3a-bc21-c692d884b39d'::uuid,'8cdfdfabeafc1f1cba660a5015720021eb8b3f8bf872f33a6464fb4871885c7d'),
  ('tutor_item_supply_private_persistent_pack_journal','d8f24cf2-8a19-4c02-babd-698fd85da56b'::uuid,'ab08edefc4e26d31bfeb10229468e226d6313500d29d15eae78fb831b8d26e24'),
  ('tutor_item_supply_private_persistent_pack_journal','e574ef33-5f88-4bc8-a9d6-c43e1c48ad22'::uuid,'8f316c8dbd4d4411c928c6749378ad52bdd254a149f5ec102e0cc82cd8532e89'),
  ('tutor_item_supply_shared_persistent_pack_journal','00507276-272e-4604-8c58-d6f92a1f12de'::uuid,'06d9e9fdc533f20bfad29e5fa7eab8a6f377dc0aec84b03136892de99aae2b76'),
  ('tutor_item_supply_shared_persistent_pack_journal','1e8f525b-8d31-4369-8345-78192c53af14'::uuid,'eeb4caed12ffcbf8bf4a3172ce673096dc301d37e82f66e10268cfa04118ea21'),
  ('tutor_item_supply_shared_persistent_pack_journal','254ad692-96ec-416b-8235-cc4dbcebdc97'::uuid,'ca4271ccc47457b76af2c06459d571a061802aac92994ff132fd43af9103e02e'),
  ('tutor_item_supply_shared_persistent_pack_journal','29bf0021-a7c4-442a-8a44-d69cc831068b'::uuid,'1a1bb9e8e4b7d2a46d47b0ba2df4baa5986c4ac106a79e37c91c1ed3d42606da'),
  ('tutor_item_supply_shared_persistent_pack_journal','3ca50c24-30f4-4cb4-8d70-f8bd1ee14f13'::uuid,'ed9817861f4cbb2e2e757c20602fc76781aeab0ae27c5511410144ba565d4455'),
  ('tutor_item_supply_shared_persistent_pack_journal','58236c04-6829-48d6-b265-28a3b8c232de'::uuid,'7fa9a52ffaaa82ef7109e773a0dcb01fdcf2cddf4e1e259cb8409f55feb55129'),
  ('tutor_item_supply_shared_persistent_pack_journal','732b65be-a3a8-4f41-bce7-b5636c609fc4'::uuid,'2e77964d9c09acd05f7fd0455a8fd1e5f4cf909a86996944730ec1a9b004b765'),
  ('tutor_item_supply_shared_persistent_pack_journal','8746c1dc-65df-4b93-9c00-ba85ae6f24d6'::uuid,'621416a63197703fdfc2fed51167f645c82cf91181cb00f4dfd581361b2a8965'),
  ('tutor_item_supply_shared_persistent_pack_journal','87507322-435e-448f-8393-4fb16b1ef561'::uuid,'bc1fb9a9443ea71c02cd372544d804cee314a63e5ffeda5fd41592baf153a91d'),
  ('tutor_item_supply_shared_persistent_pack_journal','b910459d-69ed-4ba6-b102-032455a87ed9'::uuid,'a0511b096e06fe8a6e5b0118f3e4a4241f444aab3d95a5b2d53dc52e49decb61'),
  ('tutor_item_supply_shared_persistent_pack_journal','bbd5759b-0d56-4f15-aaff-64b9f9f0732c'::uuid,'1a9abed19865a0e5cefc273c09210d13e8d7c5e110050c324127d0a3be90cf3a'),
  ('tutor_item_supply_shared_persistent_pack_journal','d1956189-c610-4a35-aff9-68016b2757c2'::uuid,'29cde71487a94efdafb76604f0184ef465781a1e3d57ea0d50fbd5be52b941e1')
 ) AS frozen(tbl,row_id,sha) LOOP
  EXECUTE format('SELECT payload_hash FROM public.%I WHERE id=$1 FOR SHARE',expected.tbl) INTO digest USING expected.row_id;
  IF digest IS DISTINCT FROM expected.sha THEN RAISE check_violation USING MESSAGE='539 retained original facts changed'; END IF;
 END LOOP;
 IF (SELECT count(*) FROM tutor_item_supply_shared_persistent_pack_journal WHERE phase_id IN(
  '8c5b0671-54ec-4f64-9412-17cd8c286d58','92f71c9e-94fd-4d7f-8bf9-9a15a920bcee','baa4d9d7-411d-452f-acf3-ed9551c12743'))<>12
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal WHERE record_kind='phase'
   AND public_task_id=(p->'task_ref'->>'public_task_id')::uuid
   AND payload_json->>'revision_id'='7ac04190-a21c-41f9-b121-353680e38fb9'
   AND phase_id NOT IN('8c5b0671-54ec-4f64-9412-17cd8c286d58','92f71c9e-94fd-4d7f-8bf9-9a15a920bcee','baa4d9d7-411d-452f-acf3-ed9551c12743'))
 THEN RAISE check_violation USING MESSAGE='539 no new ordinary phase or changed historical stage'; END IF;
 SELECT * INTO ip FROM tutor_item_supply_shared_review_investigation_preparations WHERE id='87596016-7639-4ed9-8f05-684b7bf8027c' FOR SHARE;
 SELECT * INTO ir FROM tutor_item_supply_shared_review_investigation_receipts WHERE id=ip.id FOR SHARE;
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id='a6433494-8167-4f2b-ad39-82a20ce62cde' FOR SHARE;
 IF ip.id IS NULL OR ir.id IS NULL OR a.id IS NULL OR ir.preparation_id IS DISTINCT FROM ip.id
  OR (ip.root_id,ir.root_id,a.root_id) IS DISTINCT FROM ((p->>'root_id')::uuid,(p->>'root_id')::uuid,(p->>'root_id')::uuid)
  OR (ip.job_id,ir.job_id) IS DISTINCT FROM ('b2c4f8cf-3600-4cc0-ab79-efcae56f4dd1'::uuid,'b2c4f8cf-3600-4cc0-ab79-efcae56f4dd1'::uuid)
  OR (ip.generation_artifact_id,ir.generation_artifact_id) IS DISTINCT FROM (a.id,a.id)
  OR ip.snapshot_hash IS DISTINCT FROM p->>'investigation_preparation_hash' OR ir.snapshot_hash IS DISTINCT FROM p->>'investigation_receipt_hash'
  OR (ip.reservation_id,ir.reservation_id) IS DISTINCT FROM ('07895b24-4fe9-4e76-b6e4-a3abad9093de'::uuid,'07895b24-4fe9-4e76-b6e4-a3abad9093de'::uuid)
  OR ip.payload_json->'source_deadlines' IS DISTINCT FROM p->'source_deadlines'
  OR ir.payload_json->>'safe_reason' IS DISTINCT FROM 'investigation_analysis_pending_revision_owner'
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_receipts r WHERE r.id=ir.id AND r.xmin::text::bigint<>txid_current()%4294967296)
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_preparations q WHERE q.id=ip.id AND q.xmin::text::bigint<>txid_current()%4294967296)
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations r JOIN tutor_item_supply_shared_runtime_settlements s
   ON s.reservation_id=r.id WHERE r.id=ip.reservation_id AND r.job_id=ip.job_id AND r.root_id=ip.root_id
   AND r.lease_generation=ip.lease_generation AND r.reservation_key=ip.payload_json->>'reservation_key'
   AND s.id=ir.settlement_id AND s.settlement_key=r.reservation_key AND s.usage_state='unknown'
   AND r.xmin::text::bigint<>txid_current()%4294967296 AND s.xmin::text::bigint<>txid_current()%4294967296)
  OR item_supply_internal.controlled_counterexample_held(a.job_id) IS DISTINCT FROM false
  OR item_supply_internal.controlled_counterexample_held(ip.job_id) IS DISTINCT FROM false
  OR item_supply_internal.public_native_source_current(jsonb_build_object('request',a.request_json,'ref',p->'task_ref')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='539 exact committed investigation and current source required'; END IF;
 lease_data:=p->'execution_lease';
 SELECT * INTO j FROM tutor_item_supply_shared_jobs WHERE id=(p->>'execution_job_id')::uuid FOR SHARE;
 SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=j.id FOR SHARE;
 SELECT * INTO m FROM tutor_item_supply_development_model_accounting_jobs WHERE job_id=j.id FOR SHARE;
 SELECT * INTO b FROM tutor_item_supply_development_model_accounting_batches WHERE id=m.batch_id FOR SHARE;
 snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1' THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
 IF j.id IS NULL OR c.id IS NULL OR m.job_id IS NULL OR b.id IS NULL
  OR j.root_id IS DISTINCT FROM a.root_id OR j.parent_job_id IS NOT NULL
  OR j.job_key IS DISTINCT FROM encode(sha256(convert_to(j.root_id::text||chr(31)||'revision.execution.8759601676394ed98f05684b7bf8027c','UTF8')),'hex')
  OR j.id IN('0e0accec-81ae-4f0e-b550-f80d53446e79','6bf48d8d-c32a-4ae7-b3a4-68adceae15c2','b2c4f8cf-3600-4cc0-ab79-efcae56f4dd1')
  OR c.state IS DISTINCT FROM 'leased' OR c.lease_expires_at IS NULL
  OR lease_data->>'job_id' IS DISTINCT FROM j.id::text OR lease_data->>'visibility' IS DISTINCT FROM 'public'
  OR lease_data->'owner_id' IS DISTINCT FROM 'null'::jsonb OR lease_data->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
  OR c.lease_owner IS DISTINCT FROM lease_data->>'lease_owner' OR c.lease_generation::text IS DISTINCT FROM lease_data->>'generation'
  OR c.state_version::text IS DISTINCT FROM lease_data->>'state_version' OR c.lease_generation<>1
  OR c.parent_deadline IS DISTINCT FROM (lease_data->>'parent_deadline')::timestamptz
  OR c.lease_expires_at IS DISTINCT FROM (lease_data->>'expires_at')::timestamptz
  OR snapshot IS DISTINCT FROM lease_data->'profile' OR snapshot->>'profile_hash' IS DISTINCT FROM p->>'profile_hash'
  OR snapshot->>'profile_key_hash' IS DISTINCT FROM a.request_json->'profile'->>'profile_key_hash'
  OR (snapshot->'values'->>'discussion_rounds')::integer<2 OR (snapshot->'values'->>'revision_rounds')::integer<1
  OR b.id::text IS DISTINCT FROM p->>'batch_id' OR b.root_id IS DISTINCT FROM j.root_id OR m.parent_job_id IS NOT NULL
  OR m.lease_owner IS DISTINCT FROM c.lease_owner OR m.lease_generation IS DISTINCT FROM c.lease_generation
  OR m.lease_state_version IS DISTINCT FROM c.state_version OR m.parent_deadline IS DISTINCT FROM c.parent_deadline
  OR m.profile_hash IS DISTINCT FROM snapshot->>'profile_hash'
  OR b.authorization_key IS DISTINCT FROM 'development-unlimited-model-calls-20261010'
  OR b.mode IS DISTINCT FROM 'accounting_only' OR b.cumulative_caps_enforced IS DISTINCT FROM false
  OR b.provider_key IS DISTINCT FROM 'deepseek' OR b.model IS DISTINCT FROM 'deepseek-flash'
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_parameter_profiles ep WHERE ep.profile_hash=snapshot->>'profile_hash'
   AND ep.profile_key_hash=snapshot->>'profile_key_hash' AND ep.profile_json->'profile_key'->>'provider'=b.provider_key
   AND ep.profile_json->'profile_key'->>'model_version'=b.model)
  OR b.valid_until>b.started_at+interval '7200 seconds' OR c.parent_deadline>b.valid_until
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_budget_roots r JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id
   WHERE r.id=j.root_id AND r.canonical_key=o.canonical_key AND o.provider_key=b.provider_key)
  OR item_supply_internal.controlled_counterexample_held(j.id) IS DISTINCT FROM false
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations WHERE job_id=j.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts WHERE job_id=j.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints WHERE job_id=j.id)
 THEN RAISE check_violation USING MESSAGE='539 current original517 execution lease binding required'; END IF;
 stamp:=clock_timestamp();
 IF COALESCE((p->>'issued_at')::timestamptz<=stamp AND (p->>'valid_until')::timestamptz>stamp
  AND (p->>'issued_at')::timestamptz>=b.started_at AND (p->>'valid_until')::timestamptz<=LEAST(
   c.lease_expires_at,c.parent_deadline,b.valid_until,(snapshot->>'bound_at')::timestamptz+
   (snapshot->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond'),false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='539 fresh execution expired or deadline extended'; END IF;
 FOR bound IN SELECT value FROM jsonb_array_elements(p->'source_deadlines') LOOP
  IF COALESCE((p->>'valid_until')::timestamptz<=(bound->>'retained_until')::timestamptz,false) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='539 historical source bound cannot extend'; END IF;
 END LOOP;
END $body539$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_committed_revision_execution(jsonb) FROM PUBLIC;

DO $guard539$ DECLARE a record; BEGIN SELECT p.*,l.lanname INTO a FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.fresh_committed_revision_matches(jsonb)');
 IF FOUND AND (encode(sha256(convert_to(a.prosrc,'UTF8')),'hex') IS DISTINCT FROM 'a1de0e73836967030e80c1619a8b7d2e660808b856e39eb38022314579686cb9'
  OR a.proargnames IS DISTINCT FROM ARRAY['p']::text[] OR a.prorettype IS DISTINCT FROM 'pg_catalog.bool'::regtype
  OR a.lanname<>'plpgsql' OR a.prokind<>'f' OR NOT a.prosecdef OR a.proretset OR a.proisstrict OR a.proleakproof
  OR a.provolatile<>'v' OR a.proparallel<>'u' OR a.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR a.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR a.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR a.proallargtypes IS NOT NULL OR a.proargmodes IS NOT NULL OR a.provariadic<>0 OR a.pronargdefaults<>0
  OR a.procost<>100 OR a.prorows<>0 OR a.prosupport<>0 OR a.proargdefaults IS NOT NULL OR a.probin IS NOT NULL OR a.prosqlbody IS NOT NULL)
 THEN RAISE check_violation USING MESSAGE='539 unexpected existing receiver'; END IF; END $guard539$;
CREATE OR REPLACE FUNCTION item_supply_internal.fresh_committed_revision_matches(p jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body539$
DECLARE e tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 c tutor_item_supply_shared_jobs%ROWTYPE;
BEGIN
 SELECT * INTO e FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND record_kind='committed_revision_execution'
  AND operation_key='p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution' FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 IF p->>'parent_job_id' IS DISTINCT FROM e.payload_json->>'execution_job_id' THEN RETURN false; END IF;
 PERFORM item_supply_internal.assert_committed_revision_execution(e.payload_json);
 SELECT * INTO c FROM tutor_item_supply_shared_jobs WHERE id=(p->'child_lease'->>'job_id')::uuid FOR SHARE;
 IF c.id IS NULL OR c.parent_job_id IS DISTINCT FROM (e.payload_json->>'execution_job_id')::uuid
  OR c.root_id IS DISTINCT FROM (e.payload_json->>'root_id')::uuid
  OR p->>'root_id' IS DISTINCT FROM e.payload_json->>'root_id'
  OR p->>'investigation_receipt_id' IS DISTINCT FROM e.payload_json->>'investigation_receipt_id'
  OR p->>'investigation_receipt_hash' IS DISTINCT FROM e.payload_json->>'investigation_receipt_hash'
  OR p->>'parent_artifact_id' IS DISTINCT FROM 'a6433494-8167-4f2b-ad39-82a20ce62cde'
  OR p->'parent_lease' IS DISTINCT FROM e.payload_json->'execution_lease'
  OR p->'source_deadlines' IS DISTINCT FROM e.payload_json->'source_deadlines'
  OR p->'context'->>'schema_version' IS DISTINCT FROM 'native_revision_author_context_v2'
  OR COALESCE((p->>'deadline_at')::timestamptz<=(e.payload_json->>'valid_until')::timestamptz,false) IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_development_model_accounting_jobs m WHERE m.job_id=c.id
   AND m.parent_job_id=c.parent_job_id AND m.batch_id=(e.payload_json->>'batch_id')::uuid
   AND m.profile_hash=e.payload_json->>'profile_hash')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations rp
   WHERE rp.investigation_receipt_id=(p->>'investigation_receipt_id')::uuid
    AND (rp.id IS DISTINCT FROM (p->>'preparation_id')::uuid OR rp.child_job_id IS DISTINCT FROM c.id OR rp.payload_json IS DISTINCT FROM p))
 THEN RAISE check_violation USING MESSAGE='539 exact once-bound revision child required'; END IF;
 RETURN true;
END $body539$;
REVOKE ALL ON FUNCTION item_supply_internal.fresh_committed_revision_matches(jsonb) FROM PUBLIC;

DO $guard539$ DECLARE a record; BEGIN SELECT p.*,l.lanname INTO a FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.enforce_committed_revision_execution_insert()');
 IF FOUND AND (encode(sha256(convert_to(a.prosrc,'UTF8')),'hex') IS DISTINCT FROM '00d88180d733ef764cdd2c435dece8171875063d8ff7d6150a4d2ab7d7c1e536'
  OR a.proargnames IS DISTINCT FROM NULL::text[] OR a.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype
  OR a.lanname<>'plpgsql' OR a.prokind<>'f' OR NOT a.prosecdef OR a.proretset OR a.proisstrict OR a.proleakproof
  OR a.provolatile<>'v' OR a.proparallel<>'u' OR a.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR a.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR a.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR a.proallargtypes IS NOT NULL OR a.proargmodes IS NOT NULL OR a.provariadic<>0 OR a.pronargdefaults<>0
  OR a.procost<>100 OR a.prorows<>0 OR a.prosupport<>0 OR a.proargdefaults IS NOT NULL OR a.probin IS NOT NULL OR a.prosqlbody IS NOT NULL)
 THEN RAISE check_violation USING MESSAGE='539 unexpected existing receiver'; END IF; END $guard539$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_committed_revision_execution_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body539$
DECLARE h tutor_item_supply_private_persistent_pack_journal%ROWTYPE; p jsonb:=NEW.payload_json; xid bigint:=txid_current()%4294967296;
BEGIN
 IF NEW.record_kind<>'committed_revision_execution' THEN RETURN NEW; END IF;
 SELECT * INTO h FROM tutor_item_supply_private_persistent_pack_journal WHERE id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND record_kind='task' FOR SHARE;
 IF h.id IS NULL OR (NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.intent_hash)
  IS DISTINCT FROM (h.id,h.user_id,h.epoch,h.scope_id,h.intent_hash)
  OR NEW.operation_key IS DISTINCT FROM 'p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution'
 THEN RAISE check_violation USING MESSAGE='539 canonical PRIVATE execution namespace required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('fresh-committed-revision'),hashtext('87596016-7639-4ed9-8f05-684b7bf8027c'));
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=h.id AND record_kind='committed_revision_execution')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations WHERE investigation_receipt_id='87596016-7639-4ed9-8f05-684b7bf8027c')
 THEN RAISE check_violation USING MESSAGE='539 committed revision execution once consumed'; END IF;
 PERFORM item_supply_internal.assert_committed_revision_execution(p);
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_jobs j JOIN tutor_item_supply_shared_job_controls c ON c.job_id=j.id
  JOIN tutor_item_supply_development_model_accounting_jobs m ON m.job_id=j.id
  JOIN tutor_item_supply_development_model_accounting_batches b ON b.id=m.batch_id
  WHERE j.id=(p->>'execution_job_id')::uuid AND j.xmin::text::bigint=xid AND c.xmin::text::bigint=xid
   AND m.xmin::text::bigint=xid AND b.xmin::text::bigint=xid)
 THEN RAISE check_violation USING MESSAGE='539 original same-TOP fresh graph required'; END IF;
 RETURN NEW;
END $body539$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_committed_revision_execution_insert() FROM PUBLIC;

DO $upgrade539_revision$
DECLARE actual record; verified record; source text; repaired text; definition text;
 expected_attrs constant jsonb:=$attrs539${"oid":"5374836","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"enforce_native_revision_insert","prorows":0,"pronargs":0,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"2279","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":null,"proargtypes":[],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs539$::jsonb;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.enforce_native_revision_insert()');
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='539 original receiver missing'; END IF;
 IF (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='539 exact original receiver metadata changed'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')='e550e6e6bffc52504dd5d5bd2076ee51fa698db3bfa7856c46a7fbe3e0a11a4b' THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM '15b0fbedb2def4854104b90b527ba261ba7583bd148fb7daeff76aca257cebc4'
 THEN RAISE check_violation USING MESSAGE='539 exact original receiver body changed'; END IF;
 repaired:=source;
 IF length(repaired)-length(replace(repaired,$old539_0$  persistent_permission boolean:=false; family_permission boolean:=false;$old539_0$,''))<>1*length($old539_0$  persistent_permission boolean:=false; family_permission boolean:=false;$old539_0$)
 THEN RAISE check_violation USING MESSAGE='539 exact receiver patch anchor changed'; END IF;
 repaired:=replace(repaired,$old539_0$  persistent_permission boolean:=false; family_permission boolean:=false;$old539_0$,$new539_0$  persistent_permission boolean:=false; family_permission boolean:=false; fresh_permission boolean:=false;$new539_0$);
 IF length(repaired)-length(replace(repaired,$old539_1$  -- New normal branch is closed by the SAME original investigation/phase receiver.$old539_1$,''))<>1*length($old539_1$  -- New normal branch is closed by the SAME original investigation/phase receiver.$old539_1$)
 THEN RAISE check_violation USING MESSAGE='539 exact receiver patch anchor changed'; END IF;
 repaired:=replace(repaired,$old539_1$  -- New normal branch is closed by the SAME original investigation/phase receiver.$old539_1$,$new539_1$  fresh_permission:=item_supply_internal.fresh_committed_revision_matches(p);
  -- New normal branch is closed by the SAME original investigation/phase receiver.$new539_1$);
 IF length(repaired)-length(replace(repaired,$old539_2$    PERFORM item_supply_internal.assert_persistent_normal_repair(investigation_prep.payload_json);$old539_2$,''))<>2*length($old539_2$    PERFORM item_supply_internal.assert_persistent_normal_repair(investigation_prep.payload_json);$old539_2$)
 THEN RAISE check_violation USING MESSAGE='539 exact receiver patch anchor changed'; END IF;
 repaired:=replace(repaired,$old539_2$    PERFORM item_supply_internal.assert_persistent_normal_repair(investigation_prep.payload_json);$old539_2$,$new539_2$    IF fresh_permission THEN
      IF item_supply_internal.fresh_committed_revision_matches(p) IS DISTINCT FROM true
      THEN RAISE check_violation USING MESSAGE='539 fresh revision authority changed'; END IF;
    ELSE
      PERFORM item_supply_internal.assert_persistent_normal_repair(investigation_prep.payload_json);
    END IF;$new539_2$);
 IF length(repaired)-length(replace(repaired,$old539_3$    OR investigation_row.job_id IS DISTINCT FROM parent_control.job_id$old539_3$,''))<>1*length($old539_3$    OR investigation_row.job_id IS DISTINCT FROM parent_control.job_id$old539_3$)
 THEN RAISE check_violation USING MESSAGE='539 exact receiver patch anchor changed'; END IF;
 repaired:=replace(repaired,$old539_3$    OR investigation_row.job_id IS DISTINCT FROM parent_control.job_id$old539_3$,$new539_3$    OR (NOT fresh_permission AND investigation_row.job_id IS DISTINCT FROM parent_control.job_id)$new539_3$);
 IF length(repaired)-length(replace(repaired,$old539_4$investigation_row.valid_until<=stamp OR investigation_prep.valid_until<=stamp$old539_4$,''))<>2*length($old539_4$investigation_row.valid_until<=stamp OR investigation_prep.valid_until<=stamp$old539_4$)
 THEN RAISE check_violation USING MESSAGE='539 exact receiver patch anchor changed'; END IF;
 repaired:=replace(repaired,$old539_4$investigation_row.valid_until<=stamp OR investigation_prep.valid_until<=stamp$old539_4$,$new539_4$(NOT fresh_permission AND (investigation_row.valid_until<=stamp OR investigation_prep.valid_until<=stamp))$new539_4$);
 IF length(repaired)-length(replace(repaired,$old539_5$    OR p->'parent_lease' IS DISTINCT FROM investigation_prep.payload_json->'lease'$old539_5$,''))<>1*length($old539_5$    OR p->'parent_lease' IS DISTINCT FROM investigation_prep.payload_json->'lease'$old539_5$)
 THEN RAISE check_violation USING MESSAGE='539 exact receiver patch anchor changed'; END IF;
 repaired:=replace(repaired,$old539_5$    OR p->'parent_lease' IS DISTINCT FROM investigation_prep.payload_json->'lease'$old539_5$,$new539_5$    OR (NOT fresh_permission AND p->'parent_lease' IS DISTINCT FROM investigation_prep.payload_json->'lease')$new539_5$);
 IF length(repaired)-length(replace(repaired,$old539_6$OR (p->>'deadline_at')::timestamptz>LEAST(investigation_row.valid_until,
      investigation_prep.valid_until,parent_control.lease_expires_at$old539_6$,''))<>1*length($old539_6$OR (p->>'deadline_at')::timestamptz>LEAST(investigation_row.valid_until,
      investigation_prep.valid_until,parent_control.lease_expires_at$old539_6$)
 THEN RAISE check_violation USING MESSAGE='539 exact receiver patch anchor changed'; END IF;
 repaired:=replace(repaired,$old539_6$OR (p->>'deadline_at')::timestamptz>LEAST(investigation_row.valid_until,
      investigation_prep.valid_until,parent_control.lease_expires_at$old539_6$,$new539_6$OR (p->>'deadline_at')::timestamptz>LEAST(
      CASE WHEN fresh_permission THEN parent_control.lease_expires_at ELSE investigation_row.valid_until END,
      CASE WHEN fresh_permission THEN parent_control.lease_expires_at ELSE investigation_prep.valid_until END,parent_control.lease_expires_at$new539_6$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM 'e550e6e6bffc52504dd5d5bd2076ee51fa698db3bfa7856c46a7fbe3e0a11a4b'
 THEN RAISE check_violation USING MESSAGE='539 exact patched body required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='539 definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM 'e550e6e6bffc52504dd5d5bd2076ee51fa698db3bfa7856c46a7fbe3e0a11a4b'
 THEN RAISE check_violation USING MESSAGE='539 receiver OID/metadata or patched source changed'; END IF;
END $upgrade539_revision$;

DO $upgrade539_family$
DECLARE actual record; verified record; source text; repaired text; definition text;
 expected_attrs constant jsonb:=$attrs539${"oid":"5380149","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"persistent_registered_family_revision_matches","prorows":0,"pronargs":1,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"16","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["p"],"proargtypes":["3802"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs539$::jsonb;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.persistent_registered_family_revision_matches(jsonb)');
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='539 original receiver missing'; END IF;
 IF (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='539 exact original receiver metadata changed'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')='d26c59f1019cfcbdd2b1ac95bec4f3b60659f19c7600df2d7c2e31e432436cd0' THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM '21e3c91fc8d3efb576fc456aaf17de1040e5296d66985b276e9ee610e5984ae3'
 THEN RAISE check_violation USING MESSAGE='539 exact original receiver body changed'; END IF;
 repaired:=source;
 IF length(repaired)-length(replace(repaired,$old539_0$ PERFORM item_supply_internal.assert_persistent_normal_repair(ip.payload_json);$old539_0$,''))<>1*length($old539_0$ PERFORM item_supply_internal.assert_persistent_normal_repair(ip.payload_json);$old539_0$)
 THEN RAISE check_violation USING MESSAGE='539 exact receiver patch anchor changed'; END IF;
 repaired:=replace(repaired,$old539_0$ PERFORM item_supply_internal.assert_persistent_normal_repair(ip.payload_json);$old539_0$,$new539_0$ IF item_supply_internal.fresh_committed_revision_matches(p) IS DISTINCT FROM true THEN
  PERFORM item_supply_internal.assert_persistent_normal_repair(ip.payload_json);
 END IF;$new539_0$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM 'd26c59f1019cfcbdd2b1ac95bec4f3b60659f19c7600df2d7c2e31e432436cd0'
 THEN RAISE check_violation USING MESSAGE='539 exact patched body required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='539 definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM 'd26c59f1019cfcbdd2b1ac95bec4f3b60659f19c7600df2d7c2e31e432436cd0'
 THEN RAISE check_violation USING MESSAGE='539 receiver OID/metadata or patched source changed'; END IF;
END $upgrade539_family$;

DO $kinds539$ DECLARE d text; BEGIN
 SELECT pg_get_constraintdef(oid) INTO d FROM pg_constraint
 WHERE conrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass
 AND conname='tutor_item_supply_private_persistent_pack_jou_record_kind_check' AND contype='c' AND convalidated;
 IF d IN($old539$CHECK ((record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text, 'explicit_recovery_approval'::text, 'explicit_recovery_binding'::text])))$old539$,
  $old539$CHECK (record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text, 'explicit_recovery_approval'::text, 'explicit_recovery_binding'::text]))$old539$) THEN
  ALTER TABLE tutor_item_supply_private_persistent_pack_journal DROP CONSTRAINT tutor_item_supply_private_persistent_pack_jou_record_kind_check;
  ALTER TABLE tutor_item_supply_private_persistent_pack_journal ADD CONSTRAINT tutor_item_supply_private_persistent_pack_jou_record_kind_check
   CHECK(record_kind IN('task','phase','pause','stop','private_attachment','private_status','prestart_proof','prestart_binding',
    'explicit_recovery_approval','explicit_recovery_binding','committed_revision_execution'));
 ELSIF d IS NULL OR d NOT IN($new539$CHECK ((record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text, 'explicit_recovery_approval'::text, 'explicit_recovery_binding'::text, 'committed_revision_execution'::text])))$new539$,
  $new539$CHECK (record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text, 'explicit_recovery_approval'::text, 'explicit_recovery_binding'::text, 'committed_revision_execution'::text]))$new539$)
 THEN RAISE check_violation USING MESSAGE='539 exact PRIVATE kind successor required'; END IF;
END $kinds539$;

DO $trigger539$ DECLARE t record; BEGIN
 SELECT *,pg_get_triggerdef(oid) AS definition INTO t FROM pg_trigger
 WHERE tgrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass AND tgname='a003_committed_revision_execution';
 IF FOUND THEN
  IF t.definition IS DISTINCT FROM 'CREATE TRIGGER a003_committed_revision_execution BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_committed_revision_execution_insert()'
   OR t.tgenabled<>'O' OR t.tgisinternal
  THEN RAISE check_violation USING MESSAGE='539 existing execution trigger changed'; END IF;
 ELSE CREATE TRIGGER a003_committed_revision_execution BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal
  FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_committed_revision_execution_insert(); END IF;
END $trigger539$;
