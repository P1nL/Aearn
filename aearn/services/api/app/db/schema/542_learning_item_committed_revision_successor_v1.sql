-- Explicit single successor; original functions/metadata and all unrelated receipt once identities retained.
-- No lease extension, investigation replay, historical output import, or new accounting policy.

DO $fix542_0$
DECLARE actual record; verified record; source text; repaired text; definition text;
 old_sha constant text:='c831377e715515e9c55e29492025d5e3011654b455d04c74fd49295ed63f2eaa'; new_sha constant text:='1ed3e8441df4f0204ea96fa7a22b63b84280701aec74a204ee35917cf570b003';
 expected_attrs constant jsonb:=$attrs542${"oid":"5390383","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"assert_committed_revision_execution","prorows":0,"pronargs":1,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"2278","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["p"],"proargtypes":["3802"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs542$::jsonb;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('session_replication_role')<>'origin'
 THEN RAISE check_violation USING MESSAGE='542 original sandbox only'; END IF;
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.assert_committed_revision_execution(jsonb)');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='542 original receiver metadata changed'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='542 exact original receiver required'; END IF;
 repaired:=source;
 repaired:=replace(repaired,$old542_0$OR p->>'authorization_sha256' IS DISTINCT FROM 'beb3e25f2a11f9fcb6d6bac24d17e143a9909907befc9081ed540c937df72fc1'$old542_0$,$new542_0$OR COALESCE(p->>'authorization_sha256' IN('beb3e25f2a11f9fcb6d6bac24d17e143a9909907befc9081ed540c937df72fc1','68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243'),false) IS DISTINCT FROM true$new542_0$);
 repaired:=replace(repaired,$old542_1$j.root_id::text||chr(31)||'revision.execution.8759601676394ed98f05684b7bf8027c'$old542_1$,$new542_1$j.root_id::text||chr(31)||(CASE WHEN p->>'authorization_sha256'='68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243' THEN 'revision.execution.8759601676394ed98f05684b7bf8027c.successor.1' ELSE 'revision.execution.8759601676394ed98f05684b7bf8027c' END)$new542_1$);
 repaired:=replace(repaired,$old542_2$ lease_data:=p->'execution_lease';$old542_2$,$new542_2$ -- Explicit human successor, never inferred from absent output or an expired lease.
 IF p->>'authorization_sha256'='68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243' THEN
  IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal e
    WHERE e.id='914ce88b-7f8c-4a21-9412-3fd13d0b63b7' AND e.pack_task_id=h.id
     AND (e.user_id,e.epoch,e.scope_id,e.intent_hash) IS NOT DISTINCT FROM (h.user_id,h.epoch,h.scope_id,h.intent_hash)
     AND e.record_kind='committed_revision_execution' AND e.operation_key='p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution'
     AND e.payload_hash='d2738b4e8b09848a490173f42abf6b9fe790bd5aa26a56134d199db971e2e0da'
     AND e.xmin::text::bigint<>txid_current()%4294967296)
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_preparations rp
    WHERE rp.id='c8593cb3-2360-48c0-a7f8-a3a69c930184' AND rp.investigation_receipt_id='87596016-7639-4ed9-8f05-684b7bf8027c'
     AND rp.root_id=a.root_id AND rp.parent_artifact_id=a.id
     AND rp.parent_job_id='92c0ee20-4790-45bb-bd9d-3452de213ce4' AND rp.child_job_id='755430d8-7b8f-4929-88bb-d2bf613c992c'
     AND rp.snapshot_hash='70f78e7b28e5167ad3bab05e0b8de0b0c29bfba2bfa0e51eebc9ae6bdeaa7406'
     AND rp.xmin::text::bigint<>txid_current()%4294967296)
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s
    JOIN tutor_item_supply_shared_reservations r ON r.id=s.reservation_id
    WHERE s.id='79dd27e0-bc85-464c-b666-f559ed6fbd06' AND r.id='f37b3253-1234-494c-9343-03e219ea03d9'
     AND r.job_id='755430d8-7b8f-4929-88bb-d2bf613c992c' AND r.root_id=a.root_id
     AND s.settlement_key='generation.62821446a215475c962eaaf3d025911c' AND s.usage_state='known'
     AND s.receipt_hash='f8477ab173b598afa977fc3a26ba59cd8cac01e3ef8251cc9cdd3b82cfb7d20c'
     AND s.xmin::text::bigint<>txid_current()%4294967296)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_generation_outputs WHERE preparation_id='c8593cb3-2360-48c0-a7f8-a3a69c930184')
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts WHERE job_id='755430d8-7b8f-4929-88bb-d2bf613c992c')
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints WHERE job_id='755430d8-7b8f-4929-88bb-d2bf613c992c')
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_revision_lineage WHERE preparation_id='c8593cb3-2360-48c0-a7f8-a3a69c930184')
   OR p->>'execution_job_id' IN('92c0ee20-4790-45bb-bd9d-3452de213ce4','755430d8-7b8f-4929-88bb-d2bf613c992c')
  THEN RAISE check_violation USING MESSAGE='542 exact committed predecessor and explicit successor required'; END IF;
 END IF;
 lease_data:=p->'execution_lease';$new542_2$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='542 exact successor delta required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='542 receiver definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='542 successor receiver metadata/body changed'; END IF;
END $fix542_0$;

DO $fix542_1$
DECLARE actual record; verified record; source text; repaired text; definition text;
 old_sha constant text:='a1de0e73836967030e80c1619a8b7d2e660808b856e39eb38022314579686cb9'; new_sha constant text:='8073e7bd96c64337cc7f9d4b1b2138d6e6e0c350bc3f5246baded2415916d850';
 expected_attrs constant jsonb:=$attrs542${"oid":"5390386","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"fresh_committed_revision_matches","prorows":0,"pronargs":1,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"16","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["p"],"proargtypes":["3802"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs542$::jsonb;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('session_replication_role')<>'origin'
 THEN RAISE check_violation USING MESSAGE='542 original sandbox only'; END IF;
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.fresh_committed_revision_matches(jsonb)');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='542 original receiver metadata changed'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='542 exact original receiver required'; END IF;
 repaired:=source;
 repaired:=replace(repaired,$old542_0$AND operation_key='p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution' FOR SHARE;$old542_0$,$new542_0$AND operation_key IN('p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution','p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution.successor.1')
  AND payload_json->>'execution_job_id'=p->>'parent_job_id' FOR SHARE;$new542_0$);
 repaired:=replace(repaired,$old542_1$WHERE rp.investigation_receipt_id=(p->>'investigation_receipt_id')::uuid$old542_1$,$new542_1$WHERE rp.investigation_receipt_id=(p->>'investigation_receipt_id')::uuid
    AND NOT (e.payload_json->>'authorization_sha256'='68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243' AND rp.id='c8593cb3-2360-48c0-a7f8-a3a69c930184')$new542_1$);
 repaired:=replace(repaired,$old542_2$ IF c.id IS NULL OR c.parent_job_id$old542_2$,$new542_2$ IF (e.payload_json->>'authorization_sha256'='68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243'
   AND c.job_key IS DISTINCT FROM encode(sha256(convert_to(c.root_id::text||chr(31)||'revision.8759601676394ed98f05684b7bf8027c.successor.1','UTF8')),'hex'))
  OR c.id IS NULL OR c.parent_job_id$new542_2$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='542 exact successor delta required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='542 receiver definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='542 successor receiver metadata/body changed'; END IF;
END $fix542_1$;

DO $fix542_2$
DECLARE actual record; verified record; source text; repaired text; definition text;
 old_sha constant text:='00d88180d733ef764cdd2c435dece8171875063d8ff7d6150a4d2ab7d7c1e536'; new_sha constant text:='5be96158f3bc36d27095ff115bd93b1380ebe643cc357d96d84020484b914509';
 expected_attrs constant jsonb:=$attrs542${"oid":"5390387","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"enforce_committed_revision_execution_insert","prorows":0,"pronargs":0,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"2279","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":null,"proargtypes":[],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs542$::jsonb;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('session_replication_role')<>'origin'
 THEN RAISE check_violation USING MESSAGE='542 original sandbox only'; END IF;
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.enforce_committed_revision_execution_insert()');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='542 original receiver metadata changed'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='542 exact original receiver required'; END IF;
 repaired:=source;
 repaired:=replace(repaired,$old542_0$OR NEW.operation_key IS DISTINCT FROM 'p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution'$old542_0$,$new542_0$OR NEW.operation_key IS DISTINCT FROM (CASE WHEN p->>'authorization_sha256'='68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243' THEN 'p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution.successor.1' ELSE 'p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution' END)$new542_0$);
 repaired:=replace(repaired,$old542_1$WHERE pack_task_id=h.id AND record_kind='committed_revision_execution')$old542_1$,$new542_1$WHERE pack_task_id=h.id AND record_kind='committed_revision_execution'
   AND (p->>'authorization_sha256' IS DISTINCT FROM '68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243' OR operation_key=NEW.operation_key))$new542_1$);
 repaired:=replace(repaired,$old542_2$WHERE investigation_receipt_id='87596016-7639-4ed9-8f05-684b7bf8027c')$old542_2$,$new542_2$WHERE investigation_receipt_id='87596016-7639-4ed9-8f05-684b7bf8027c'
   AND (p->>'authorization_sha256' IS DISTINCT FROM '68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243' OR id<>'c8593cb3-2360-48c0-a7f8-a3a69c930184'))$new542_2$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='542 exact successor delta required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='542 receiver definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='542 successor receiver metadata/body changed'; END IF;
END $fix542_2$;

DO $fix542_3$
DECLARE actual record; verified record; source text; repaired text; definition text;
 old_sha constant text:='e550e6e6bffc52504dd5d5bd2076ee51fa698db3bfa7856c46a7fbe3e0a11a4b'; new_sha constant text:='a23f9ecce6e34c8c2c9d3c7e12c0760ebd7b07ee8f92168879164d55befbe41b';
 expected_attrs constant jsonb:=$attrs542${"oid":"5374836","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"enforce_native_revision_insert","prorows":0,"pronargs":0,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"2279","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":null,"proargtypes":[],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs542$::jsonb;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('session_replication_role')<>'origin'
 THEN RAISE check_violation USING MESSAGE='542 original sandbox only'; END IF;
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.enforce_native_revision_insert()');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='542 original receiver metadata changed'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='542 exact original receiver required'; END IF;
 repaired:=source;
 repaired:=replace(repaired,$old542_0$  IF TG_TABLE_NAME='tutor_item_supply_shared_revision_preparations' THEN$old542_0$,$new542_0$  IF TG_TABLE_NAME='tutor_item_supply_shared_revision_preparations' THEN
    IF NEW.investigation_receipt_id='87596016-7639-4ed9-8f05-684b7bf8027c' AND NEW.id<>'c8593cb3-2360-48c0-a7f8-a3a69c930184' THEN
      IF fresh_permission IS DISTINCT FROM true OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal e
       WHERE e.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND e.record_kind='committed_revision_execution'
        AND e.operation_key='p7.committed-revision.6739d3c5661944ce970f0ab1e49f3acc.8759601676394ed98f05684b7bf8027c.execution.successor.1'
        AND e.payload_json->>'authorization_sha256'='68860baaac9273f5b952392ac094315e5042e13c7b75325c3b6ab3936ea95243'
        AND e.payload_json->>'execution_job_id'=NEW.parent_job_id::text)
      THEN RAISE check_violation USING MESSAGE='542 registered successor preparation required'; END IF;
    END IF;$new542_0$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='542 exact successor delta required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='542 receiver definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='542 successor receiver metadata/body changed'; END IF;
END $fix542_3$;

-- Only the registered receipt gets one preparation per strictly authorized parent.
-- All other receipts retain the original global once constraint through a partial UNIQUE.
DO $once542$
DECLARE actual record; expected record; actual_index record;
 expected_attrs constant jsonb:=$attrs542${"oid":"5374747","conbin":null,"conkey":[6],"confkey":null,"conname":"tutor_item_supply_shared_revision__investigation_receipt_id_key","contype":"u","conindid":"5374746","conrelid":"5374728","contypid":"0","conexclop":null,"conffeqop":null,"confrelid":"0","conpfeqop":null,"conppeqop":null,"conislocal":true,"condeferred":false,"confdeltype":" ","confupdtype":" ","coninhcount":0,"conparentid":"0","connamespace":"2200","connoinherit":true,"convalidated":true,"condeferrable":false,"confmatchtype":" ","confdelsetcols":null}$attrs542$::jsonb;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='542 original sandbox only'; END IF;
 LOCK TABLE public.tutor_item_supply_shared_revision_preparations IN ACCESS EXCLUSIVE MODE;
 SELECT c.* INTO actual FROM pg_constraint c
  WHERE c.conrelid='public.tutor_item_supply_shared_revision_preparations'::regclass AND c.conname='tutor_item_supply_shared_revision__investigation_receipt_id_key';
 IF FOUND THEN
  IF to_jsonb(actual) IS DISTINCT FROM expected_attrs
   OR pg_get_constraintdef(actual.oid) IS DISTINCT FROM 'UNIQUE (investigation_receipt_id)'
   OR pg_get_indexdef(actual.conindid) IS DISTINCT FROM $index542$CREATE UNIQUE INDEX tutor_item_supply_shared_revision__investigation_receipt_id_key ON public.tutor_item_supply_shared_revision_preparations USING btree (investigation_receipt_id)$index542$
   OR EXISTS(SELECT 1 FROM pg_depend d WHERE d.refclassid='pg_class'::regclass AND d.refobjid=actual.conindid)
   OR EXISTS(SELECT 1 FROM pg_depend d WHERE d.refclassid='pg_constraint'::regclass AND d.refobjid=actual.oid
    AND (d.classid,d.objid,d.objsubid,d.refobjsubid,d.deptype) IS DISTINCT FROM
      ('pg_class'::regclass,actual.conindid,0,0,'i'::"char"))
   OR to_regclass('public.revision_receipt_once_other') IS NOT NULL
   OR to_regclass('public.revision_receipt_once_successor') IS NOT NULL
  THEN RAISE check_violation USING MESSAGE='542 exact original receipt once constraint/index required'; END IF;
  ALTER TABLE public.tutor_item_supply_shared_revision_preparations
   DROP CONSTRAINT tutor_item_supply_shared_revision__investigation_receipt_id_key;
  CREATE UNIQUE INDEX revision_receipt_once_other ON public.tutor_item_supply_shared_revision_preparations USING btree (investigation_receipt_id) WHERE (investigation_receipt_id <> '87596016-7639-4ed9-8f05-684b7bf8027c'::uuid);
  CREATE UNIQUE INDEX revision_receipt_once_successor ON public.tutor_item_supply_shared_revision_preparations USING btree (investigation_receipt_id, parent_job_id) WHERE (investigation_receipt_id = '87596016-7639-4ed9-8f05-684b7bf8027c'::uuid);
 END IF;
 FOR expected IN SELECT * FROM (VALUES
  ('revision_receipt_once_other',$index542$CREATE UNIQUE INDEX revision_receipt_once_other ON public.tutor_item_supply_shared_revision_preparations USING btree (investigation_receipt_id) WHERE (investigation_receipt_id <> '87596016-7639-4ed9-8f05-684b7bf8027c'::uuid)$index542$,1),
  ('revision_receipt_once_successor',$index542$CREATE UNIQUE INDEX revision_receipt_once_successor ON public.tutor_item_supply_shared_revision_preparations USING btree (investigation_receipt_id, parent_job_id) WHERE (investigation_receipt_id = '87596016-7639-4ed9-8f05-684b7bf8027c'::uuid)$index542$,2)
 ) AS wanted(name,definition,key_count) LOOP
  SELECT i.*,c.relowner INTO actual_index FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
   WHERE i.indexrelid=to_regclass('public.'||expected.name);
  IF NOT FOUND OR actual_index.indrelid IS DISTINCT FROM 'public.tutor_item_supply_shared_revision_preparations'::regclass
   OR NOT actual_index.indisunique OR NOT actual_index.indisvalid OR NOT actual_index.indisready OR NOT actual_index.indislive
   OR actual_index.indnkeyatts<>expected.key_count OR actual_index.indnatts<>expected.key_count
   OR actual_index.indisprimary OR actual_index.indisexclusion OR NOT actual_index.indimmediate
   OR actual_index.relowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR pg_get_indexdef(actual_index.indexrelid) IS DISTINCT FROM expected.definition
  THEN RAISE check_violation USING MESSAGE='542 exact successor receipt once indexes required'; END IF;
 END LOOP;
END $once542$;
