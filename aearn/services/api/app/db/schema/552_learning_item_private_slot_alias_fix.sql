-- Exact SQL524 PRIVATE slot receiver correction: one query-local alias only.
-- Caller owns the isolated transaction and serialized installation. No commit,
-- capability, budget, task/slot/root/lease predicate or historical SQL mutation.
DO $fix552$
DECLARE
 actual record; verified record; definition text;
 old_body constant text := $old552$
DECLARE t record;c record;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=task AND pack_task_id=task
  AND user_id=u AND epoch=e AND scope_id=scope AND record_kind='task' FOR SHARE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(t.payload_json->'slots') s
  WHERE s->>'slot_id'=slot::text AND s->>'logical_item_id'=item::text) THEN RETURN false; END IF;
 SELECT j.root_id,j.scope_id,c.* INTO c FROM tutor_item_supply_private_jobs j JOIN tutor_item_supply_private_job_controls c
  ON c.job_id=j.id AND c.user_id=j.user_id AND c.epoch=j.epoch
  WHERE j.id=job AND j.user_id=u AND j.epoch=e AND j.root_id=root AND j.scope_id=scope FOR SHARE OF j,c;
 IF NOT FOUND OR c.state NOT IN('leased','generating','validating','reviewing','investigating','revising','simulating','admitting') THEN RETURN false; END IF;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal ph
  WHERE ph.pack_task_id=task AND ph.user_id=u AND ph.epoch=e AND ph.scope_id=scope AND ph.record_kind='phase'
  AND ph.payload_json->>'schema_version'='private_native_phase_v1' AND ph.payload_json->>'root_id'=root::text
  AND ph.payload_json->>'job_id'=job::text AND ph.payload_json->>'slot_id'=slot::text
  AND ph.payload_json->>'business_item_id'=item::text
  AND ph.payload_json->'lease'->>'generation'=c.lease_generation::text
  AND ph.payload_json->'lease'->>'lease_owner'=c.lease_owner
  AND (ph.payload_json->>'valid_until')::timestamptz>clock_timestamp()) THEN RETURN false; END IF;
 stamp:=clock_timestamp();
 RETURN c.lease_expires_at>stamp AND c.parent_deadline>stamp;
END $old552$;
 new_body constant text := $new552$
DECLARE t record;c record;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=task AND pack_task_id=task
  AND user_id=u AND epoch=e AND scope_id=scope AND record_kind='task' FOR SHARE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(t.payload_json->'slots') s
  WHERE s->>'slot_id'=slot::text AND s->>'logical_item_id'=item::text) THEN RETURN false; END IF;
 SELECT j.root_id,j.scope_id,ctrl.* INTO c FROM tutor_item_supply_private_jobs j JOIN tutor_item_supply_private_job_controls ctrl
  ON ctrl.job_id=j.id AND ctrl.user_id=j.user_id AND ctrl.epoch=j.epoch
  WHERE j.id=job AND j.user_id=u AND j.epoch=e AND j.root_id=root AND j.scope_id=scope FOR SHARE OF j,ctrl;
 IF NOT FOUND OR c.state NOT IN('leased','generating','validating','reviewing','investigating','revising','simulating','admitting') THEN RETURN false; END IF;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal ph
  WHERE ph.pack_task_id=task AND ph.user_id=u AND ph.epoch=e AND ph.scope_id=scope AND ph.record_kind='phase'
  AND ph.payload_json->>'schema_version'='private_native_phase_v1' AND ph.payload_json->>'root_id'=root::text
  AND ph.payload_json->>'job_id'=job::text AND ph.payload_json->>'slot_id'=slot::text
  AND ph.payload_json->>'business_item_id'=item::text
  AND ph.payload_json->'lease'->>'generation'=c.lease_generation::text
  AND ph.payload_json->'lease'->>'lease_owner'=c.lease_owner
  AND (ph.payload_json->>'valid_until')::timestamptz>clock_timestamp()) THEN RETURN false; END IF;
 stamp:=clock_timestamp();
 RETURN c.lease_expires_at>stamp AND c.parent_deadline>stamp;
END $new552$;
BEGIN
 SELECT p.*,l.lanname INTO actual FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang
 WHERE p.oid=pg_catalog.to_regprocedure(
  'item_supply_internal.private_pack_slot_current(uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_pack_slot_current'
  OR actual.lanname IS DISTINCT FROM 'plpgsql' OR actual.prokind<>'f'
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.bool'::regtype
  OR actual.pronargs<>8 OR actual.proargtypes IS DISTINCT FROM
   pg_catalog.format('%1$s %1$s %1$s %1$s %1$s %2$s %1$s %1$s',
    'pg_catalog.uuid'::regtype::oid,'pg_catalog.int8'::regtype::oid)::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['task','slot','item','root','u','e','scope','job']
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='552 original slot receiver identity/attributes changed'; END IF;
 -- SQL524 revoked PUBLIC execution. Preserve its actual owner and entire ACL;
 -- no owner/ACL is guessed from another function's deployment metadata.
 IF EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(actual.proacl,
       pg_catalog.acldefault('f',actual.proowner))) AS privilege
     WHERE privilege.grantee=0 AND privilege.privilege_type='EXECUTE')
 THEN RAISE check_violation USING MESSAGE='552 original slot receiver PUBLIC privilege changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='552 original slot receiver body changed'; END IF;
 -- The original definition retains all non-body properties; do not DROP/CREATE.
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='552 original slot receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.*,l.lanname INTO verified FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='552 slot receiver metadata/OID/owner/ACL or repaired body changed'; END IF;
END $fix552$;
