-- Exact authorized gen3 python_reference successor; no grant, fetch or wallet at install.
-- Independent of543. Existing498 table/transport receivers remain the original dispatch chain.
DO $function544$
DECLARE
 actual record; verified record; definition text; source text;
 old_sha constant text:='bf089f1f305886f4f83f03f2c0b6ffbcd4edf8d9b122aefb05ac059a6fec3b73';
 new_sha constant text:='ba17bd890627d091faacae9cbcfe98d8cceac5cb7a4cc091a93982293cc2288a';
 expected_attrs constant jsonb:=$attrs544${"oid":"5349838","proacl":null,"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"rag_registered_course_refresh_check","prorows":0,"pronargs":2,"proowner":"5313402","proconfig":["TimeZone=UTC"],"proretset":false,"prosecdef":false,"prorettype":"2278","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["grant_row","dispatch_check"],"proargtypes":["5349763","16"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"2200","proallargtypes":null,"proargdefaults":"({CONST :consttype 16 :consttypmod -1 :constcollid 0 :constlen 1 :constbyval true :constisnull false :location 6433 :constvalue 1 [ 0 0 0 0 0 0 0 0 ]})","pronargdefaults":1}$attrs544$::jsonb;
 repaired constant text:=$body544$
DECLARE original_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE middle_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_capture rag_registered_source_captures%ROWTYPE;
DECLARE latest_policy rag_registered_source_policies%ROWTYPE;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
DECLARE root_row rag_budget_authority_roots%ROWTYPE;
DECLARE latest_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE middle_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE correction rag_registered_final_followup_allowances%ROWTYPE;
DECLARE snapshot jsonb;
DECLARE url text;
DECLARE subject text;
DECLARE facet text;
DECLARE license text;
DECLARE expected_count integer;
DECLARE expected_unknown integer;
DECLARE actual_count integer;
DECLARE actual_unknown integer;
DECLARE db_now timestamptz;
DECLARE successor boolean := grant_row.id='fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid;
DECLARE predecessor rag_registered_course_refresh_authorizations%ROWTYPE;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR
    current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'course refresh owned database and read committed required' USING ERRCODE='23514';
 END IF;
 SELECT * INTO original_row FROM rag_registered_fetch_attempts
  WHERE id=grant_row.canonical_original_attempt_id FOR UPDATE;
 SELECT * INTO latest_row FROM rag_registered_fetch_attempts WHERE id=grant_row.latest_attempt_id FOR SHARE;
 SELECT * INTO latest_capture FROM rag_registered_source_captures WHERE id=grant_row.latest_capture_id FOR SHARE;
 SELECT * INTO latest_policy FROM rag_registered_source_policies WHERE policy_id=latest_row.policy_id FOR SHARE;
 SELECT * INTO policy_row FROM rag_registered_source_policies WHERE policy_id=grant_row.policy_id FOR SHARE;
 SELECT * INTO root_row FROM rag_budget_authority_roots WHERE root_id=grant_row.root_id FOR SHARE;
 db_now:=clock_timestamp();
 CASE grant_row.target_key
 WHEN 'python_reference' THEN url:='https://docs.python.org/3/reference/simple_stmts.html';subject:='route.python';facet:='fundamentals';license:='psf-2.0';
 WHEN 'sqlite_select' THEN url:='https://www.sqlite.org/lang_select.html';subject:='route.sql';facet:='queries';license:='sqlite-public-domain';
 WHEN 'sqlite_expression' THEN url:='https://www.sqlite.org/lang_expr.html';subject:='route.sql';facet:='queries';license:='sqlite-public-domain';
 WHEN 'sqlite_functions' THEN url:='https://www.sqlite.org/lang_corefunc.html';subject:='route.sql';facet:='queries';license:='sqlite-public-domain';
 WHEN 'learnx_python' THEN url:='https://learnxinyminutes.com/python/';subject:='route.python';facet:='fundamentals';license:='cc-by-sa-3.0';
 ELSE RAISE EXCEPTION 'course refresh unsupported target' USING ERRCODE='23514';
 END CASE;
 expected_count:=CASE WHEN successor THEN 2 WHEN grant_row.target_key='sqlite_select' THEN 3 ELSE 1 END;
 expected_unknown:=CASE WHEN expected_count=3 THEN 1 ELSE 0 END;
 SELECT count(*),count(*) FILTER(WHERE state='unknown') INTO actual_count,actual_unknown
  FROM rag_registered_fetch_attempts WHERE canonical_url_sha256=grant_row.canonical_url_sha256;
 snapshot:=rag_registered_course_refresh_lineage(grant_row.canonical_url_sha256);
 IF grant_row.authorization_id<>'aearn-development-20260927' OR
    grant_row.canonical_url_sha256<>encode(digest(url,'sha256'),'hex') OR
    original_row.id IS NULL OR original_row.supplemental_authorization_id IS NOT NULL OR
    original_row.state<>'settled' OR original_row.generation<>1 OR
    original_row.root_id<>grant_row.canonical_accounting_root_id OR
    original_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
    latest_row.id IS NULL OR latest_row.state<>'settled' OR
    latest_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
    actual_count<>expected_count OR actual_unknown<>expected_unknown OR
    grant_row.carried_dispatch_units<>actual_count OR grant_row.carried_unknown_units<>actual_unknown OR
    grant_row.cumulative_dispatch_ceiling<>actual_count+1 OR grant_row.additional_dispatch_units<>1 OR
    grant_row.lineage_snapshot IS DISTINCT FROM snapshot OR
    grant_row.lineage_sha256<>encode(digest(snapshot::text,'sha256'),'hex') OR
    (SELECT count(*) FROM rag_registered_fetch_attempts WHERE canonical_url_sha256=grant_row.canonical_url_sha256
      AND supplemental_authorization_id IS NULL)<>1 OR
    EXISTS(SELECT 1 FROM rag_registered_course_refresh_authorizations r
      WHERE (r.canonical_original_attempt_id=original_row.id OR r.canonical_url_sha256=grant_row.canonical_url_sha256)
        AND r.id<>grant_row.id
        AND NOT (successor AND r.id='46207149-ab55-5054-9821-da9059c0a77a'::uuid)) OR
    grant_row.issued_at>db_now OR db_now-grant_row.issued_at>interval '30 minutes' OR
    grant_row.source_expires_at<=db_now OR grant_row.source_expires_at>grant_row.issued_at+interval '7 days' OR
    grant_row.source_expires_at>grant_row.source_permission_expires_at OR
    grant_row.source_expires_at>grant_row.retention_permission_expires_at OR
    (dispatch_check AND grant_row.dispatch_expires_at<=db_now) THEN
  RAISE EXCEPTION 'course refresh lineage counter or lifetime denied' USING ERRCODE='23514';
 END IF;
 -- Every old policy/root is naturally expired, not revived or silently widened.
 IF latest_policy.policy_id IS NULL OR latest_policy.canonical_url<>url OR
    latest_policy.subject_id<>subject OR latest_policy.subject_version<>'1.0' OR
    latest_policy.facets<>ARRAY[facet] OR latest_policy.license_id<>license OR
    latest_policy.origin<>(CASE WHEN grant_row.target_key='learnx_python' THEN 'tutorial' ELSE 'official' END) OR
    latest_policy.reading_level<>'beginner' OR
    latest_policy.allowed_usages<>(CASE WHEN grant_row.target_key='learnx_python' THEN ARRAY['main_teaching']
      WHEN grant_row.target_key='sqlite_select' THEN ARRAY['assessment_evidence']
      ELSE ARRAY['assessment_evidence','main_teaching'] END) OR
    EXISTS(SELECT 1 FROM rag_registered_source_policies p JOIN rag_registered_fetch_attempts a ON a.policy_id=p.policy_id
      JOIN rag_budget_authority_roots r ON r.root_id=a.root_id
      WHERE a.canonical_url_sha256=grant_row.canonical_url_sha256 AND
       (p.enabled IS NOT TRUE OR p.revoked_at IS NOT NULL OR p.expires_at>db_now OR p.retention_until>db_now
        OR p.immutable_history_allowed IS NOT TRUE OR r.enabled IS NOT TRUE OR r.delegation_expires_at>db_now
        OR r.period_end>db_now OR policy_row.max_captured_bytes>p.max_captured_bytes
        OR ROW(r.policy_id,r.policy_generation) IS DISTINCT FROM ROW(p.policy_id,p.generation)
        OR ROW(p.subject_id,p.subject_version,p.facets,p.origin,p.reading_level,p.canonical_url,p.host,p.path,p.license_id,p.allowed_usages)
          IS DISTINCT FROM ROW(latest_policy.subject_id,latest_policy.subject_version,latest_policy.facets,latest_policy.origin,
            latest_policy.reading_level,latest_policy.canonical_url,latest_policy.host,latest_policy.path,latest_policy.license_id,latest_policy.allowed_usages))) OR
    EXISTS(SELECT 1 FROM rag_registered_source_captures c JOIN rag_registered_fetch_attempts a ON a.id=c.fetch_attempt_id
      WHERE a.canonical_url_sha256=grant_row.canonical_url_sha256 AND
       (c.cleared_at IS NOT NULL OR c.captured_body IS NULL OR c.transport_proof IS NULL OR
        c.provider_attempt_id IS NOT NULL OR c.evidence_level<>'live_egress_attested' OR
        c.transport_proof_sha256 IS NULL OR c.attestor_key_sha256 IS NULL OR c.worker_image_sha256 IS NULL OR
        c.retention_until>db_now OR c.fetched_sha256<>a.response_sha256 OR c.captured_bytes<>a.response_bytes OR
        encode(digest(c.captured_body,'sha256'),'hex')<>c.fetched_sha256 OR
        octet_length(c.captured_body)<>c.captured_bytes OR
        encode(digest(c.transport_proof,'sha256'),'hex')<>c.transport_proof_sha256)) OR
    latest_capture.id IS NULL OR latest_capture.fetch_attempt_id<>latest_row.id OR
    latest_capture.fetched_sha256<>grant_row.latest_capture_sha256 OR latest_capture.cleared_at IS NOT NULL OR
    latest_capture.captured_body IS NULL OR latest_capture.transport_proof_sha256 IS NULL OR
    latest_capture.attestor_key_sha256 IS NULL OR latest_capture.worker_image_sha256 IS NULL THEN
  RAISE EXCEPTION 'course refresh historical authority denied' USING ERRCODE='23514';
 END IF;
 IF successor THEN
  SELECT * INTO predecessor FROM rag_registered_course_refresh_authorizations
   WHERE id='46207149-ab55-5054-9821-da9059c0a77a'::uuid FOR SHARE;
  SELECT * INTO latest_auth FROM rag_registered_supplemental_authorizations
   WHERE id=latest_row.supplemental_authorization_id FOR SHARE;
  IF grant_row.target_key<>'python_reference' OR
     grant_row.canonical_original_attempt_id<>'6b01e22b-856e-413b-b8d8-05a7f1dfc61f'::uuid OR
     grant_row.canonical_accounting_root_id<>'root.course.python_reference.20261003' OR
     grant_row.latest_attempt_id<>'ee050b7c-a7ec-583f-8b01-d2b0259f3510'::uuid OR
     grant_row.latest_capture_id<>'7fabac26-245d-48d3-8d0e-8a176cbf4a86'::uuid OR
     grant_row.policy_id<>'source.course-refresh.20261013.python_reference' OR grant_row.generation<>3 OR
     grant_row.supplemental_authorization_id<>'f0662a63-3a94-55a6-ac82-139be4a0ed29'::uuid OR
     grant_row.dispatch_id<>'942b3631-a026-5c77-bc75-bae62dbf3e4a'::uuid OR
     grant_row.operation_key<>'course.refresh.20261006.fbfabcf0f3365b1298248b0b2782b69c' OR
     predecessor.id IS NULL OR latest_auth.id IS NULL OR
     latest_auth.id<>'26b2b080-1aa2-5fdd-a530-6fcbc5cb89e8'::uuid OR
     ROW(predecessor.canonical_original_attempt_id,predecessor.canonical_accounting_root_id,
         predecessor.canonical_url_sha256,predecessor.latest_attempt_id,predecessor.dispatch_id,
         predecessor.policy_id,predecessor.generation,predecessor.root_id,predecessor.supplemental_authorization_id)
       IS DISTINCT FROM ROW(original_row.id,original_row.root_id,grant_row.canonical_url_sha256,original_row.id,
         latest_row.id,latest_row.policy_id,2,latest_row.root_id,latest_auth.id) OR
     ROW(latest_auth.course_refresh_authorization_id,latest_auth.dispatch_id,latest_auth.prior_attempt_id,
         latest_auth.policy_id,latest_auth.generation,latest_auth.root_id,latest_auth.request_hash)
       IS DISTINCT FROM ROW(predecessor.id,latest_row.id,original_row.id,latest_row.policy_id,2,
         latest_row.root_id,latest_row.request_hash) OR
     latest_auth.explicit_followup_id IS NOT NULL OR latest_auth.replaces_authorization_id IS NOT NULL OR
     latest_row.generation<>2 OR latest_row.dispatched_at<original_row.settled_at OR
     latest_policy.source_handle<>'source.course.python_reference' OR
     jsonb_array_length(snapshot->'captures')<>2 OR jsonb_array_length(snapshot->'authorizations')<>0 OR
     jsonb_array_length(snapshot->'allowances')<>0 OR jsonb_array_length(snapshot->'revocations')<>0 OR
     EXISTS(SELECT 1 FROM rag_registered_supplemental_revocations WHERE authorization_id=latest_auth.id) THEN
   RAISE EXCEPTION '544 exact python reference successor lineage denied' USING ERRCODE='23514';
  END IF;
 ELSIF expected_count=1 THEN
  IF latest_row.id<>original_row.id OR jsonb_array_length(snapshot->'captures')<>1 OR
     jsonb_array_length(snapshot->'authorizations')<>0 OR jsonb_array_length(snapshot->'allowances')<>0 OR
     jsonb_array_length(snapshot->'revocations')<>0 THEN
   RAISE EXCEPTION 'course refresh ordinary lineage denied' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT * INTO middle_row FROM rag_registered_fetch_attempts WHERE canonical_url_sha256=grant_row.canonical_url_sha256 AND state='unknown';
  SELECT * INTO middle_auth FROM rag_registered_supplemental_authorizations WHERE id=middle_row.supplemental_authorization_id;
  SELECT * INTO latest_auth FROM rag_registered_supplemental_authorizations WHERE id=latest_row.supplemental_authorization_id;
  SELECT * INTO correction FROM rag_registered_final_followup_allowances WHERE id=latest_auth.explicit_followup_id;
  IF latest_row.generation<>3 OR middle_row.generation<>1 OR
     middle_row.error_code IS DISTINCT FROM 'EGRESS_UNVERIFIED_SIGNATURE_PID_NAMESPACE' OR
     middle_row.response_sha256 IS NOT NULL OR middle_row.response_bytes IS NOT NULL OR
     middle_row.settled_at IS NOT NULL OR middle_row.dispatched_at<original_row.settled_at OR
     latest_row.dispatched_at<middle_row.dispatched_at OR middle_auth.id IS NULL OR latest_auth.id IS NULL OR
     middle_auth.prior_attempt_id<>original_row.id OR middle_auth.dispatch_id<>middle_row.id OR
     middle_auth.explicit_followup_id IS NOT NULL OR middle_auth.replaces_authorization_id IS NOT NULL OR
     latest_auth.prior_attempt_id<>original_row.id OR latest_auth.dispatch_id<>latest_row.id OR
     correction.id IS NULL OR correction.generation<>3 OR correction.original_attempt_id<>original_row.id OR
     correction.latest_attempt_id<>middle_row.id OR correction.authorization_id<>latest_auth.id OR
     correction.settled_source_failed_authorization_id IS DISTINCT FROM middle_auth.id OR
     correction.settled_source_capture_id IS NULL OR correction.settled_source_capture_sha256 IS NULL OR
     NOT EXISTS(SELECT 1 FROM rag_registered_source_captures WHERE id=correction.settled_source_capture_id
       AND fetch_attempt_id=original_row.id AND fetched_sha256=correction.settled_source_capture_sha256) OR
     correction.settled_source_capture_sha256<>(SELECT fetched_sha256 FROM rag_registered_source_captures
       WHERE id=correction.settled_source_capture_id AND fetch_attempt_id=original_row.id) OR
     latest_policy.source_handle<>(SELECT source_handle FROM rag_registered_source_policies WHERE policy_id=middle_row.policy_id) OR
     jsonb_array_length(snapshot->'captures')<>2 OR jsonb_array_length(snapshot->'authorizations')<>2 OR
     jsonb_array_length(snapshot->'allowances')<>1 OR jsonb_array_length(snapshot->'revocations')<>0 THEN
   RAISE EXCEPTION 'course refresh exact SELECT correction chain denied' USING ERRCODE='23514';
  END IF;
 END IF;
 -- This new access root is NOT a core budget and has no new budget period/reservation.
 IF policy_row.policy_id IS NULL OR root_row.root_id IS NULL OR
    grant_row.root_id<>(CASE WHEN successor THEN 'root.course-refresh.20261006.python_reference.successor.20261013'
      ELSE 'root.course-refresh.20261006.'||grant_row.target_key END) OR
    policy_row.root_id<>root_row.root_id OR policy_row.generation<>latest_row.generation+1 OR
    grant_row.generation<>policy_row.generation OR policy_row.enabled IS NOT TRUE OR policy_row.revoked_at IS NOT NULL OR
    ROW(policy_row.source_handle,policy_row.subject_id,policy_row.subject_version,policy_row.facets,policy_row.origin,
      policy_row.reading_level,policy_row.canonical_url,policy_row.canonical_url_sha256,policy_row.host,policy_row.path,
      policy_row.license_id,policy_row.allowed_usages,policy_row.immutable_history_allowed)
      IS DISTINCT FROM ROW(latest_policy.source_handle,latest_policy.subject_id,latest_policy.subject_version,latest_policy.facets,
        latest_policy.origin,latest_policy.reading_level,latest_policy.canonical_url,latest_policy.canonical_url_sha256,latest_policy.host,
        latest_policy.path,latest_policy.license_id,latest_policy.allowed_usages,latest_policy.immutable_history_allowed) OR
    policy_row.max_captured_bytes>latest_policy.max_captured_bytes OR
    policy_row.expires_at<>grant_row.source_expires_at OR policy_row.retention_until<>grant_row.source_expires_at OR
    root_row.enabled IS NOT TRUE OR root_row.policy_id<>policy_row.policy_id OR root_row.policy_generation<>policy_row.generation OR
    root_row.cap_units<>grant_row.cumulative_dispatch_ceiling OR root_row.period_key<>'source-access-only.20261006' OR
    root_row.period_start<>grant_row.issued_at OR root_row.period_end<>grant_row.source_expires_at OR
    root_row.delegation_expires_at<>grant_row.source_expires_at OR root_row.delegation_generation<>1 OR
    root_row.delegation_id<>'delegation.course-refresh.'||replace(grant_row.id::text,'-','') OR
    EXISTS(SELECT 1 FROM rag_budget_periods WHERE root_id=root_row.root_id) OR
    EXISTS(SELECT 1 FROM rag_budget_reservations WHERE root_id=root_row.root_id) THEN
  RAISE EXCEPTION 'course refresh access root and exact rights denied' USING ERRCODE='23514';
 END IF;
END $body544$;
 default_at integer;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
  RAISE check_violation USING MESSAGE='544 B1d only'; END IF;
 SELECT p.* INTO actual FROM pg_proc p
 WHERE p.oid=to_regprocedure('public.rag_registered_course_refresh_check(rag_registered_course_refresh_authorizations,boolean)');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs THEN
  RAISE check_violation USING MESSAGE='544 original receiver metadata changed'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha OR
    encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha THEN
  RAISE check_violation USING MESSAGE='544 exact prior receiver required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source) THEN
  RAISE check_violation USING MESSAGE='544 original definition framing changed'; END IF;
 definition:=replace(definition,source,repaired);
 -- Preserve the existing false default's pg_node_tree source location as well as its semantics.
 -- CREATE OR REPLACE otherwise changes ONLY that parser offset in proargdefaults.
 default_at:=strpos(definition,'DEFAULT false')-1+length('DEFAULT ');
 IF default_at<length('DEFAULT ') OR default_at>6433 THEN
  RAISE check_violation USING MESSAGE='544 original default framing changed'; END IF;
 definition:=replace(definition,'DEFAULT false','DEFAULT '||repeat(' ',6433-default_at)||'false');
 EXECUTE definition;
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs OR
    encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha THEN
  RAISE check_violation USING MESSAGE='544 receiver metadata or successor body changed'; END IF;
END $function544$;

-- Keep all composite FKs and dispatch/policy/root/supplemental uniqueness intact.
-- The old slot remains globally once. Only the fixed successor UUID is outside it;
-- its existing primary key and exact receiver permit at most one additional row.
DO $constraints544$
DECLARE spec record; candidate record; matches integer; table_oid oid;
 expected_index text;
BEGIN
 table_oid:='public.rag_registered_course_refresh_authorizations'::regclass;
 LOCK TABLE public.rag_registered_course_refresh_authorizations IN ACCESS EXCLUSIVE MODE;
 FOR spec IN SELECT * FROM (VALUES
 ('CHECK ((generation = ANY (ARRAY[2, 4])))','CHECK (((generation = ANY (ARRAY[2, 4])) OR ((id = ''fbfabcf0-f336-5b12-9824-8b0b2782b69c''::uuid) AND (target_key = ''python_reference''::text) AND (generation = 3))))'),
 ('CHECK ((carried_dispatch_units = ANY (ARRAY[1, 3])))','CHECK (((carried_dispatch_units = ANY (ARRAY[1, 3])) OR ((id = ''fbfabcf0-f336-5b12-9824-8b0b2782b69c''::uuid) AND (target_key = ''python_reference''::text) AND (carried_dispatch_units = 2))))'),
 ('CHECK ((root_id = (''root.course-refresh.20261006.''::text || target_key)))','CHECK (((root_id = (''root.course-refresh.20261006.''::text || target_key)) OR ((id = ''fbfabcf0-f336-5b12-9824-8b0b2782b69c''::uuid) AND (target_key = ''python_reference''::text) AND (root_id = ''root.course-refresh.20261006.python_reference.successor.20261013''::text))))')
 ) AS checks(old_def,new_def) LOOP
  SELECT count(*) INTO matches FROM pg_constraint
   WHERE conrelid=table_oid AND contype='c' AND convalidated AND pg_get_constraintdef(oid)=spec.new_def;
  IF matches=1 THEN CONTINUE; END IF;
  SELECT count(*) INTO matches FROM pg_constraint
   WHERE conrelid=table_oid AND contype='c' AND pg_get_constraintdef(oid)=spec.old_def AND convalidated;
  IF matches<>1 THEN RAISE check_violation USING MESSAGE='544 exact prior CHECK required'; END IF;
  SELECT conname INTO candidate FROM pg_constraint
   WHERE conrelid=table_oid AND contype='c' AND pg_get_constraintdef(oid)=spec.old_def;
  EXECUTE format('ALTER TABLE public.rag_registered_course_refresh_authorizations DROP CONSTRAINT %I',candidate.conname);
  EXECUTE format('ALTER TABLE public.rag_registered_course_refresh_authorizations ADD CONSTRAINT %I %s',candidate.conname,spec.new_def);
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=table_oid AND conname=candidate.conname
     AND convalidated AND pg_get_constraintdef(oid)=spec.new_def) THEN
   RAISE check_violation USING MESSAGE='544 exact successor CHECK required'; END IF;
 END LOOP;
 FOR spec IN SELECT * FROM (VALUES
 ('UNIQUE (authorization_id, canonical_original_attempt_id)','uq_rag_course_refresh_544_original','authorization_id, canonical_original_attempt_id'),
 ('UNIQUE (authorization_id, canonical_url_sha256)','uq_rag_course_refresh_544_url','authorization_id, canonical_url_sha256')
 ) AS uniques(old_def,index_name,key_sql) LOOP
  expected_index:=format('CREATE UNIQUE INDEX %I ON public.rag_registered_course_refresh_authorizations USING btree (%s) WHERE (id <> %L::uuid)',
   spec.index_name,spec.key_sql,'fbfabcf0-f336-5b12-9824-8b0b2782b69c');
  SELECT count(*) INTO matches FROM pg_constraint WHERE conrelid=table_oid AND contype='u'
   AND pg_get_constraintdef(oid)=spec.old_def;
  IF to_regclass('public.'||spec.index_name) IS NULL THEN
   IF matches<>1 THEN RAISE check_violation USING MESSAGE='544 exact prior once UNIQUE required'; END IF;
   SELECT conname,conindid INTO candidate FROM pg_constraint WHERE conrelid=table_oid AND contype='u'
    AND pg_get_constraintdef(oid)=spec.old_def;
   IF EXISTS(SELECT 1 FROM pg_constraint WHERE contype='f' AND conindid=candidate.conindid) THEN
    RAISE check_violation USING MESSAGE='544 once UNIQUE has dependent FK'; END IF;
   EXECUTE format('ALTER TABLE public.rag_registered_course_refresh_authorizations DROP CONSTRAINT %I',candidate.conname);
   EXECUTE expected_index;
  ELSIF matches<>0 THEN
   RAISE check_violation USING MESSAGE='544 ambiguous once successor catalog';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_index i WHERE i.indexrelid=to_regclass('public.'||spec.index_name)
   AND i.indrelid=table_oid AND i.indisunique AND i.indisvalid AND i.indisready
   AND i.indnkeyatts=2 AND i.indnatts=2 AND pg_get_indexdef(i.indexrelid)=expected_index) THEN
   RAISE check_violation USING MESSAGE='544 exact successor once index required'; END IF;
 END LOOP;
END $constraints544$;
