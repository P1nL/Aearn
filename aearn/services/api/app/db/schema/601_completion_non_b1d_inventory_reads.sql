-- Forward-only correction for the original cutover actual-D inventory joins.
-- 599/600 are installed and frozen. No data, function, write ACL or source grant changes.
-- The installer must compare the complete known predecessor catalog under its
-- schema lock before applying this fragment; unknown/partial states still deny.
SET LOCAL search_path=pg_catalog,public,item_supply_internal,completion_baseline_internal,pg_temp;
DO $inventory_scope$
DECLARE
 identity_row record;
 relation_name text;
 relation_row record;
 runtime_oid oid;
BEGIN
 IF current_database() NOT IN ('postgres','aearn_completion_b_test_20261026','aearn_completion_b_validation_20261027')
  OR NOT (SELECT rolsuper FROM pg_roles WHERE rolname=session_user) THEN
  RAISE EXCEPTION 'completion inventory: named database and schema installer required' USING ERRCODE='42501';
 END IF;
 SELECT * INTO STRICT identity_row FROM completion_baseline_internal.contract_identity();
 IF identity_row.contract_id<>'completion_non_b1d_v1'
  OR identity_row.database_name<>current_database()
  OR identity_row.database_oid<>(SELECT oid FROM pg_database WHERE datname=current_database())
  OR identity_row.purpose<>(CASE WHEN current_database()='aearn_completion_b_validation_20261027'
       THEN 'storage-validation-purpose' ELSE 'runtime-purpose' END) THEN
  RAISE EXCEPTION 'completion inventory: protected database identity changed' USING ERRCODE='42501';
 END IF;
 SELECT oid INTO runtime_oid FROM pg_roles WHERE rolname='aearn_cb_runtime_20261027'
  AND rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolcreatedb
  AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
  AND shobj_description(oid,'pg_authid')='completion_non_b1d_v1 managed role';
 IF runtime_oid IS NULL OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid=runtime_oid OR member=runtime_oid) THEN
  RAISE EXCEPTION 'completion inventory: runtime identity changed' USING ERRCODE='42501';
 END IF;
 FOREACH relation_name IN ARRAY ARRAY['public.rag_source_reviews','public.rag_source_admissions','public.rag_source_claim_receipts'] LOOP
  SELECT c.* INTO relation_row FROM pg_class c WHERE c.oid=to_regclass(relation_name);
  IF NOT FOUND OR relation_row.relkind<>'r' OR pg_get_userbyid(relation_row.relowner)<>'postgres'
   OR relation_row.relrowsecurity OR relation_row.relforcerowsecurity THEN
   RAISE EXCEPTION 'completion inventory: predecessor relation changed' USING ERRCODE='23514';
  END IF;
  -- This is a one-way old-to-new delta. A COMPLETE caller is a readonly no-op;
  -- raw replay or a partially applied/unknown runtime ACL must not be accepted.
  IF EXISTS(SELECT 1 FROM aclexplode(COALESCE(relation_row.relacl,acldefault('r',relation_row.relowner))) a
      WHERE a.grantee IN(0,runtime_oid))
   OR EXISTS(SELECT 1 FROM pg_attribute c CROSS JOIN LATERAL aclexplode(c.attacl) a
      WHERE c.attrelid=relation_row.oid AND c.attnum>0 AND NOT c.attisdropped AND a.grantee IN(0,runtime_oid)) THEN
   RAISE EXCEPTION 'completion inventory: predecessor runtime ACL changed' USING ERRCODE='23514';
  END IF;
 END LOOP;
END $inventory_scope$;

-- actual_d_lifecycle.actual_d_private_counts: fixed owner-scoped joins at 119-124.
GRANT SELECT ON TABLE public.rag_source_reviews TO aearn_cb_runtime_20261027;
GRANT SELECT ON TABLE public.rag_source_admissions TO aearn_cb_runtime_20261027;
GRANT SELECT ON TABLE public.rag_source_claim_receipts TO aearn_cb_runtime_20261027;
